# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError
import logging
import os
import base64
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class CloudStorageSyncService(models.Model):
    _name = 'cloud_storage.sync.service'
    _description = 'Cloud Storage Synchronization Service'

    def _get_google_drive_service(self, auth_config):
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            
            if not auth_config.access_token:
                raise UserError("No access token available for authentication")
            
            # Check if token is expired and refresh if needed
            if auth_config.token_expiry and auth_config.token_expiry <= fields.Datetime.now():
                _logger.info(f"Token expired for {auth_config.name}, attempting refresh")
                if not auth_config.refresh_access_token():
                    raise UserError("Failed to refresh expired access token")
                
            credentials = Credentials(
                token=auth_config.access_token,
                refresh_token=auth_config.refresh_token,
                client_id=auth_config.client_id,
                client_secret=auth_config.client_secret,
                token_uri='https://accounts.google.com/o/oauth2/token'
            )
            
            # Build service and check if token needs refresh
            service = build('drive', 'v3', credentials=credentials)
            
            # If credentials were refreshed, update them in database
            if credentials.token != auth_config.access_token:
                auth_config.write({
                    'access_token': credentials.token,
                    'token_expiry': datetime.now() + timedelta(seconds=3600)  # Default 1 hour
                })
                _logger.info(f"Updated refreshed token for auth config {auth_config.name}")
            
            return service
            
        except Exception as e:
            _logger.error(f"Error creating Google Drive service: {str(e)}")
            raise UserError(f"Error connecting to Google Drive: {str(e)}")

    def _create_virtual_attachment(self, record, field_name, file_name):
        """Create a virtual attachment object for image fields"""
        class VirtualAttachment:
            def __init__(self, datas, name, record_id):
                self.datas = datas
                self.name = name
                self.id = f"virtual_{record_id}_{field_name}"
                
        image_data = getattr(record, field_name)
        return VirtualAttachment(image_data, file_name, record.id)

    def _update_attachment_to_cloud(self, attachment, drive_file, original_file_content, config):
        """Update attachment to use cloud storage while maintaining preview functionality"""
        try:
            # Store original local data as backup information
            original_size = len(original_file_content) if original_file_content else 0
            
            # Store original local path before updating
            original_local_path = f"attachment_{attachment.id}" if hasattr(attachment, 'id') else None
            
            # Get base URL for controller access
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
            
            # Update attachment with cloud storage info
            update_values = {
                # Keep type as 'binary' but store cloud URL for fallback
                # This allows previews to work while having cloud backup
                'type': 'binary',  # Keep as binary for preview compatibility
                'url': f"{base_url}/cloud_storage/file/{attachment.id}",  # Use our proxy controller
                'file_size': original_size,  # Keep original file size
                'mimetype': attachment.mimetype or 'application/octet-stream',
                'description': f"Synced to Google Drive: {drive_file['web_view_link']}",
                # Cloud storage specific fields
                'cloud_storage_url': drive_file['web_view_link'],
                'cloud_file_id': drive_file['id'],
                'cloud_sync_status': 'synced',
                'cloud_synced_date': datetime.now(),
                'original_local_path': original_local_path
            }
            
            # Only clear local data if explicitly configured
            if config.delete_local_after_sync:
                # Instead of setting type='url', we'll keep it as 'binary' but clear datas
                # This prevents Odoo from redirecting and allows our methods to handle it
                update_values['datas'] = False
                update_values['checksum'] = False
                # Store the cloud URL in a separate field for our methods to use
                update_values['url'] = False  # Clear any URL to prevent redirects
            
            attachment.write(update_values)
            
            # Optionally delete local file data to save disk space
            if config.delete_local_after_sync:
                self._delete_local_file(attachment)
            
            _logger.info(f"Updated attachment {attachment.name} with cloud storage info: {drive_file['web_content_link']}")
            
        except Exception as e:
            _logger.error(f"Error updating attachment {attachment.name} to cloud: {str(e)}")
            # Don't raise exception here to avoid breaking the sync process
            
    def _delete_local_file(self, attachment):
        """Delete local file data after successful cloud sync"""
        try:
            # Clear the datas field is already done in update_values
            # This method can be extended to handle physical file deletion if needed
            _logger.info(f"Local file data cleared for {attachment.name} to save disk space")
        except Exception as e:
            _logger.error(f"Error deleting local file for {attachment.name}: {str(e)}")
            
    def _create_drive_folder(self, service, folder_name, parent_id=None):
        try:
            existing = service.files().list(
                q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields='files(id, name)'
            ).execute()
            
            if existing.get('files'):
                return existing['files'][0]['id']
            
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            
            if parent_id:
                folder_metadata['parents'] = [parent_id]
                
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            return folder.get('id')
            
        except Exception as e:
            _logger.error(f"Error creating Drive folder: {str(e)}")
            raise UserError(f"Error creating folder in Drive: {str(e)}")

    def _upload_file_to_drive(self, service, file_content, file_name, folder_id=None):
        try:
            from googleapiclient.http import MediaIoBaseUpload
            import io
            
            file_metadata = {'name': file_name}
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            media = MediaIoBaseUpload(
                io.BytesIO(file_content), 
                mimetype='application/octet-stream',
                resumable=True
            )
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,webViewLink,webContentLink'
            ).execute()
            
            service.permissions().create(
                fileId=file.get('id'),
                body={'role': 'reader', 'type': 'anyone'}
            ).execute()
            
            return {
                'id': file.get('id'),
                'web_view_link': file.get('webViewLink'),
                'web_content_link': file.get('webContentLink')
            }
            
        except Exception as e:
            _logger.error(f"Error uploading file to Drive: {str(e)}")
            raise UserError(f"Error uploading file: {str(e)}")

    def _get_files_to_sync(self, config, limit_per_model=None):
        """Get files to sync with improved logic - uses same approach as complete_sync"""
        files_to_sync = []
        
        # Get allowed extensions upfront
        allowed_extensions = config.file_type_ids.filtered('is_active').mapped('extension')
        if not allowed_extensions:
            _logger.warning("No active file types configured")
            return files_to_sync
        
        _logger.info(f"[MANUAL_SYNC] Starting sync with allowed extensions: {allowed_extensions}")
        
        for model_config in config.model_config_ids.filtered('is_active'):
            try:
                # Check if model exists before trying to access it
                if model_config.model_name not in self.env:
                    _logger.warning(f"Model {model_config.model_name} does not exist in this Odoo instance. Skipping.")
                    continue
                
                model_name = model_config.model_name
                batch_size = limit_per_model or 500  # Use provided limit or default to 500
                
                _logger.info(f"[MANUAL_SYNC] Processing model: {model_name} with limit: {batch_size}")
                
                # Use the same efficient logic as complete_sync
                if model_name == 'ir.attachment':
                    # Efficient query for attachments
                    domain = [
                        ('res_model', '!=', False),
                        ('type', '=', 'binary'),
                        ('file_size', '>', 0),
                        ('file_size', '<=', 100 * 1024 * 1024),
                        ('cloud_sync_status', 'in', ['local', 'error']),
                        ('name', '!=', False),  # Not null
                        ('name', '!=', ''),     # Not empty
                        ('name', 'like', '%.%')  # Must contain a dot
                    ]
                    
                    # Add extension filter
                    _logger.info(f"[MANUAL_SYNC] Adding extension filter for ir.attachment. Allowed extensions: {allowed_extensions}")
                    try:
                        extension_domains = []
                        for ext in allowed_extensions:
                            if ext and len(ext) > 0:  # Ensure extension is valid
                                extension_domains.append(('name', 'ilike', f'%.{ext}'))
                        
                        if extension_domains:
                            if len(extension_domains) > 1:
                                domain.append('|' * (len(extension_domains) - 1))
                            domain.extend(extension_domains)
                        
                        _logger.info(f"[MANUAL_SYNC] Final domain for ir.attachment: {domain}")
                    except Exception as e:
                        _logger.error(f"[MANUAL_SYNC] Error building extension filter: {str(e)}")
                        raise
                    
                    attachments = self.env['ir.attachment'].search(
                        domain, 
                        limit=batch_size,
                        order='id ASC'
                    )
                    
                    _logger.info(f"[MANUAL_SYNC] Found {len(attachments)} attachments for ir.attachment")
                    
                    for i, attachment in enumerate(attachments):
                        _logger.debug(f"[MANUAL_SYNC] Processing attachment {i+1}/{len(attachments)}: ID={attachment.id}, name='{attachment.name}'")
                        try:
                            # Safe extension extraction
                            if attachment.name and '.' in attachment.name:
                                file_extension = attachment.name.split('.')[-1].lower()
                            else:
                                _logger.debug(f"Skipping attachment {attachment.id}: no valid file extension in name '{attachment.name}'")
                                continue
                                
                            if file_extension and file_extension in allowed_extensions:
                                files_to_sync.append({
                                    'record': attachment,
                                    'attachment': attachment,
                                    'model_config': model_config,
                                    'file_extension': file_extension
                                })
                            else:
                                _logger.debug(f"Skipping attachment {attachment.id}: extension '{file_extension}' not in allowed extensions")
                        except Exception as e:
                            _logger.error(f"Error processing attachment {attachment.id} in ir.attachment: {str(e)}")
                            continue
                
                elif model_name in ['account.move', 'account.invoice', 'purchase.order', 'sale.order']:
                    # For document models, look for related attachments
                    attachment_domain = [
                        ('res_model', '=', model_name),
                        ('type', '=', 'binary'),
                        ('file_size', '>', 0),
                        ('file_size', '<=', 100 * 1024 * 1024),
                        ('cloud_sync_status', 'in', ['local', 'error']),
                        ('name', '!=', False),  # Not null
                        ('name', '!=', ''),     # Not empty
                        ('name', 'like', '%.%')  # Must contain a dot
                    ]
                    
                    # Add extension filter
                    _logger.info(f"[MANUAL_SYNC] Adding extension filter for {model_name}. Allowed extensions: {allowed_extensions}")
                    try:
                        extension_domains = []
                        for ext in allowed_extensions:
                            if ext and len(ext) > 0:  # Ensure extension is valid
                                extension_domains.append(('name', 'ilike', f'%.{ext}'))
                        
                        if extension_domains:
                            if len(extension_domains) > 1:
                                attachment_domain.append('|' * (len(extension_domains) - 1))
                            attachment_domain.extend(extension_domains)
                        
                        _logger.info(f"[MANUAL_SYNC] Final domain for {model_name}: {attachment_domain}")
                    except Exception as e:
                        _logger.error(f"[MANUAL_SYNC] Error building extension filter for {model_name}: {str(e)}")
                        raise
                    
                    attachments = self.env['ir.attachment'].search(
                        attachment_domain,
                        limit=batch_size,
                        order='id ASC'
                    )
                    
                    _logger.info(f"[MANUAL_SYNC] Found {len(attachments)} attachments for {model_name}")
                    
                    for i, attachment in enumerate(attachments):
                        _logger.debug(f"[MANUAL_SYNC] Processing attachment {i+1}/{len(attachments)} for {model_name}: ID={attachment.id}, name='{attachment.name}'")
                        try:
                            # Skip record existence check for problematic models and process attachment directly
                            if model_name == 'account.move':
                                _logger.debug(f"Processing account.move attachment {attachment.id} without record check due to SQL issues")
                                if attachment.name and '.' in attachment.name:
                                    file_extension = attachment.name.split('.')[-1].lower()
                                    if file_extension and file_extension in allowed_extensions:
                                        # Use attachment as both record and attachment for compatibility
                                        files_to_sync.append({
                                            'record': attachment,  # Use attachment as record fallback
                                            'attachment': attachment,
                                            'model_config': model_config,
                                            'file_extension': file_extension
                                        })
                                    else:
                                        _logger.debug(f"Skipping attachment {attachment.id}: extension '{file_extension}' not in allowed extensions")
                                else:
                                    _logger.debug(f"Skipping attachment {attachment.id}: no valid file extension in name '{attachment.name}'")
                            else:
                                # For other models, try normal record check
                                if attachment.res_id:
                                    try:
                                        # Use with_context to avoid loading unnecessary fields that might cause SQL errors
                                        record = self.env[model_name].with_context(active_test=False).browse(attachment.res_id)
                                        # Test if record exists without triggering field loading
                                        if record.exists():
                                            # Safe extension extraction
                                            if attachment.name and '.' in attachment.name:
                                                file_extension = attachment.name.split('.')[-1].lower()
                                            else:
                                                _logger.debug(f"Skipping attachment {attachment.id}: no valid file extension in name '{attachment.name}'")
                                                continue
                                                
                                            if file_extension and file_extension in allowed_extensions:
                                                files_to_sync.append({
                                                    'record': record,
                                                    'attachment': attachment,
                                                    'model_config': model_config,
                                                    'file_extension': file_extension
                                                })
                                            else:
                                                _logger.debug(f"Skipping attachment {attachment.id}: extension '{file_extension}' not in allowed extensions")
                                        else:
                                            _logger.debug(f"Skipping attachment {attachment.id}: related record {attachment.res_id} doesn't exist in model {model_name}")
                                    except Exception as record_error:
                                        _logger.warning(f"Error accessing record {attachment.res_id} in model {model_name}: {str(record_error)}. Using attachment directly.")
                                        # If we can't access the record due to SQL errors, still process the attachment
                                        if attachment.name and '.' in attachment.name:
                                            file_extension = attachment.name.split('.')[-1].lower()
                                            if file_extension and file_extension in allowed_extensions:
                                                # Create a dummy record object for compatibility
                                                files_to_sync.append({
                                                    'record': attachment,  # Use attachment as record fallback
                                                    'attachment': attachment,
                                                    'model_config': model_config,
                                                    'file_extension': file_extension
                                                })
                        except Exception as e:
                            _logger.error(f"Error processing attachment {attachment.id} for {model_name}: {str(e)}")
                            continue
                
                elif model_name in ['res.partner', 'hr.employee']:
                    # Only process if jpg is allowed
                    if 'jpg' in allowed_extensions:
                        base_domain = []
                        if model_name == 'res.partner':
                            base_domain = [
                                '|', ('is_company', '=', True), ('customer_rank', '>', 0),
                                ('image_1920', '!=', False)
                            ]
                        elif model_name == 'hr.employee':
                            base_domain = [('image_1920', '!=', False)]
                        
                        records = self.env[model_name].search(
                            base_domain,
                            limit=batch_size,
                            order='id ASC'
                        )
                        
                        for record in records:
                            if getattr(record, model_config.field_name):
                                file_name = f"{record.display_name or record.name}_{model_config.field_name}.jpg"
                                files_to_sync.append({
                                    'record': record,
                                    'attachment': self._create_virtual_attachment(record, model_config.field_name, file_name),
                                    'model_config': model_config,
                                    'file_extension': 'jpg'
                                })
                
                _logger.info(f"[MANUAL_SYNC] Found {len([f for f in files_to_sync if f['model_config'].model_name == model_name])} files for {model_name}")
                                    
            except Exception as e:
                _logger.error(f"Error getting files for model {model_config.model_name}: {str(e)}")
                continue
                
        _logger.info(f"[MANUAL_SYNC] Total files to sync: {len(files_to_sync)}")
        return files_to_sync

    def _sync_file(self, file_info, service, config):
        try:
            attachment = file_info['attachment']
            model_config = file_info['model_config']
            record = file_info['record']
            
            if not attachment.datas:
                return {
                    'status': 'error',
                    'message': 'No file data available',
                    'file_name': attachment.name
                }
            
            # Check file size before processing to prevent memory errors
            try:
                file_size = attachment.file_size or 0
                # Limit file size to 100MB to prevent memory issues
                max_file_size = 100 * 1024 * 1024  # 100MB in bytes
                
                if file_size > max_file_size:
                    return {
                        'status': 'error',
                        'message': f'File too large ({file_size / (1024*1024):.1f}MB). Maximum allowed: 100MB',
                        'file_name': attachment.name
                    }
                
                file_content = base64.b64decode(attachment.datas)
                
            except MemoryError:
                return {
                    'status': 'error',
                    'message': f'Memory error: File too large to process ({attachment.file_size / (1024*1024):.1f}MB)',
                    'file_name': attachment.name
                }
            except Exception as decode_error:
                return {
                    'status': 'error',
                    'message': f'Error decoding file data: {str(decode_error)}',
                    'file_name': attachment.name
                }
            
            folder_id = None
            if model_config.drive_folder_name:
                folder_id = self._create_drive_folder(service, model_config.drive_folder_name)
            
            drive_file = self._upload_file_to_drive(
                service, file_content, attachment.name, folder_id
            )
            
            # Update attachment to point to Google Drive if configured
            if config.replace_local_with_cloud:
                self._update_attachment_to_cloud(attachment, drive_file, file_content, config)
            
            sync_log = self.env['cloud_storage.sync.log'].create({
                'sync_type': 'manual',
                'status': 'success',
                'model_name': model_config.model_name,
                'record_id': record.id,
                'file_name': attachment.name,
                'original_path': f"attachment_{attachment.id}",
                'drive_url': drive_file['web_view_link'],
                'drive_file_id': drive_file['id'],
                'file_size_bytes': len(file_content),
                'config_id': config.id
            })
            
            return {
                'status': 'success',
                'file_name': attachment.name,
                'drive_url': drive_file['web_view_link'],
                'log_id': sync_log.id
            }
            
        except Exception as e:
            error_msg = str(e)
            _logger.error(f"Error syncing file {attachment.name}: {error_msg}")
            
            self.env['cloud_storage.sync.log'].create({
                'sync_type': 'manual',
                'status': 'error',
                'model_name': model_config.model_name,
                'record_id': record.id,
                'file_name': attachment.name,
                'error_message': error_msg,
                'config_id': config.id
            })
            
            return {
                'status': 'error',
                'file_name': attachment.name,
                'message': error_msg
            }

    def manual_sync(self):
        config = self.env['cloud_storage.config'].get_active_config()
        if not config:
            raise UserError("No active configuration found")
        
        if not config.auth_id or config.auth_id.state != 'authorized':
            raise UserError("Google Drive authentication not configured or expired")
        
        service = self._get_google_drive_service(config.auth_id)
        files_to_sync = self._get_files_to_sync(config)
        
        if not files_to_sync:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': "No files found to synchronize",
                    'type': 'info'
                }
            }
        
        results = {
            'success': [],
            'errors': [],
            'total': len(files_to_sync)
        }
        
        for file_info in files_to_sync:
            result = self._sync_file(file_info, service, config)
            
            if result['status'] == 'success':
                results['success'].append(result)
            else:
                results['errors'].append(result)
        
        success_count = len(results['success'])
        error_count = len(results['errors'])
        
        message = f"Sync completed: {success_count} success, {error_count} errors out of {results['total']} files"
        notification_type = 'success' if error_count == 0 else 'warning'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': notification_type
            }
        }

    @api.model
    def automatic_sync(self):
        configs = self.env['cloud_storage.config'].search([
            ('is_active', '=', True),
            ('auto_sync', '=', True)
        ])
        
        for config in configs:
            try:
                if not config.auth_id or config.auth_id.state != 'authorized':
                    _logger.warning(f"Skipping auto sync for config {config.name}: authentication not valid")
                    continue
                
                service = self._get_google_drive_service(config.auth_id)
                files_to_sync = self._get_files_to_sync(config)
                
                _logger.info(f"Starting automatic sync for config {config.name}: {len(files_to_sync)} files")
                
                for file_info in files_to_sync:
                    try:
                        result = self._sync_file(file_info, service, config)
                        result['sync_type'] = 'automatic'
                        
                        if result['status'] == 'success':
                            _logger.info(f"Successfully synced file: {result['file_name']}")
                        else:
                            _logger.error(f"Failed to sync file: {result['file_name']} - {result.get('message', 'Unknown error')}")
                            
                    except Exception as e:
                        _logger.error(f"Error during automatic sync of file: {str(e)}")
                        continue
                
            except Exception as e:
                _logger.error(f"Error during automatic sync for config {config.name}: {str(e)}")
                continue
        
        return True

    def complete_sync(self, batch_size=50):
        """Optimized complete sync with efficient filtering and batch processing"""
        config = self.env['cloud_storage.config'].get_active_config()
        if not config:
            raise UserError("No active configuration found")
        
        if not config.auth_id or config.auth_id.state != 'authorized':
            raise UserError("Google Drive authentication not configured or expired")
        
        # Get allowed extensions upfront
        allowed_extensions = config.file_type_ids.filtered('is_active').mapped('extension')
        if not allowed_extensions:
            raise UserError("No active file types configured")
        
        _logger.info(f"[COMPLETE_SYNC] Starting complete sync with allowed extensions: {allowed_extensions}")
        
        # Initialize or get existing sync session
        sync_session = self._get_or_create_sync_session(config)
        
        service = self._get_google_drive_service(config.auth_id)
        
        total_processed = 0
        session_success = 0
        session_errors = 0
        
        # Process each active model configuration
        for model_config in config.model_config_ids.filtered('is_active'):
            _logger.info(f"[COMPLETE_SYNC] Processing model: {model_config.model_name}")
            
            # Get efficient count of pending files for this model
            pending_count = self._count_pending_files(model_config, allowed_extensions)
            _logger.info(f"[COMPLETE_SYNC] Found {pending_count} pending files for {model_config.model_name}")
            
            if pending_count == 0:
                continue
            
            # Process in batches
            offset = 0
            model_processed = 0
            
            while model_processed < pending_count:
                # Get batch of files to sync
                batch_files = self._get_batch_files_to_sync(
                    model_config, allowed_extensions, batch_size, offset
                )
                
                if not batch_files:
                    break
                
                _logger.info(f"[COMPLETE_SYNC] Processing batch {offset//batch_size + 1} for {model_config.model_name}: {len(batch_files)} files")
                
                # Process batch
                batch_results = self._process_sync_batch(batch_files, service, config, sync_session)
                
                session_success += batch_results['success']
                session_errors += batch_results['errors']
                model_processed += len(batch_files)
                total_processed += len(batch_files)
                
                # Update session progress
                self._update_sync_session_progress(sync_session, batch_results)
                
                # Commit after each batch to avoid losing progress
                self.env.cr.commit()
                
                _logger.info(f"[COMPLETE_SYNC] Batch completed. Success: {batch_results['success']}, Errors: {batch_results['errors']}")
                
                offset += batch_size
                
                # Small delay to prevent overwhelming the system
                import time
                time.sleep(0.1)
        
        # Mark session as completed
        sync_session.write({
            'status': 'completed',
            'end_time': fields.Datetime.now(),
            'total_success': session_success,
            'total_errors': session_errors,
            'total_processed': total_processed
        })
        
        _logger.info(f"[COMPLETE_SYNC] Complete sync finished. Total: {total_processed}, Success: {session_success}, Errors: {session_errors}")
        
        message = f"Complete sync finished: {session_success} success, {session_errors} errors out of {total_processed} files processed"
        notification_type = 'success' if session_errors == 0 else 'warning'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': notification_type
            }
        }
    
    def _get_files_to_sync_for_model(self, config, model_config):
        """Get all files for a specific model without pagination"""
        files_to_sync = []
        
        try:
            # Check if model exists before trying to access it
            if model_config.model_name not in self.env:
                _logger.warning(f"Model {model_config.model_name} does not exist in this Odoo instance. Skipping.")
                return files_to_sync
            
            # Additional check for common model name variations
            model_name = model_config.model_name
            if model_name == 'document.document' and 'ir.attachment' in self.env:
                model_name = 'ir.attachment'
                _logger.info(f"Redirecting document.document to ir.attachment model")
                
            Model = self.env[model_name]
            
            # Define domain for each model type
            domain = []
            if model_name == 'ir.attachment':
                max_file_size = 100 * 1024 * 1024  # 100MB limit
                domain = [
                    ('res_model', '!=', False),      # Only attachments linked to records
                    ('type', '=', 'binary'),         # Only binary attachments
                    ('file_size', '>', 0),           # Only files with actual content
                    ('file_size', '<=', max_file_size)  # Skip files too large for memory
                ]
            elif model_name == 'res.partner':
                domain = [
                    '|', ('is_company', '=', True), ('customer_rank', '>', 0),
                    ('image_1920', '!=', False)
                ]
            elif model_name == 'hr.employee':
                domain = [('image_1920', '!=', False)]
            
            # Process in batches of 100 to avoid memory issues
            batch_size = 100
            offset = 0
            
            while True:
                records = Model.search(domain, limit=batch_size, offset=offset)
                if not records:
                    break
                
                for record in records:
                    try:
                        if hasattr(record, model_config.field_name):
                            attachment_field = getattr(record, model_config.field_name)
                            
                            if attachment_field:
                                # Handle different types of attachment fields
                                if model_name == 'ir.attachment':
                                    if hasattr(record, 'datas') and hasattr(record, 'name') and record.name:
                                        # Check file size first to avoid memory issues
                                        file_size = getattr(record, 'file_size', 0)
                                        max_file_size = 100 * 1024 * 1024  # 100MB
                                        
                                        if file_size > max_file_size:
                                            _logger.warning(f"Skipping large file {record.name}: {file_size / (1024*1024):.1f}MB > 100MB limit")
                                            continue
                                        
                                        if record.datas:  # Check if has actual data
                                            file_extension = record.name.split('.')[-1].lower() if '.' in record.name else ''
                                            allowed_extensions = config.file_type_ids.filtered('is_active').mapped('extension')
                                            
                                            if allowed_extensions and file_extension in allowed_extensions:
                                                # Check if already synced
                                                existing_log = self.env['cloud_storage.sync.log'].search([
                                                    ('model_name', '=', model_name),
                                                    ('record_id', '=', record.id),
                                                    ('file_name', '=', record.name),
                                                    ('status', '=', 'success')
                                                ], limit=1)
                                                
                                                if not existing_log:
                                                    files_to_sync.append({
                                                        'record': record,
                                                        'attachment': record,
                                                        'model_config': model_config,
                                                        'file_extension': file_extension
                                                    })
                                
                                elif model_config.field_name in ['image_1920', 'image_1024', 'image_512', 'image_256', 'image_128']:
                                    allowed_extensions = config.file_type_ids.filtered('is_active').mapped('extension')
                                    
                                    if allowed_extensions and 'jpg' in allowed_extensions:
                                        file_name = f"{record.display_name or record.name}_{model_config.field_name}.jpg"
                                        
                                        # Check if already synced
                                        existing_log = self.env['cloud_storage.sync.log'].search([
                                            ('model_name', '=', model_name),
                                            ('record_id', '=', record.id),
                                            ('file_name', '=', file_name),
                                            ('status', '=', 'success')
                                        ], limit=1)
                                        
                                        if not existing_log:
                                            files_to_sync.append({
                                                'record': record,
                                                'attachment': self._create_virtual_attachment(record, model_config.field_name, file_name),
                                                'model_config': model_config,
                                                'file_extension': 'jpg'
                                            })
                                
                                else:
                                    if hasattr(attachment_field, 'datas') and hasattr(attachment_field, 'name'):
                                        file_extension = attachment_field.name.split('.')[-1].lower() if '.' in attachment_field.name else ''
                                        allowed_extensions = config.file_type_ids.filtered('is_active').mapped('extension')
                                        
                                        if allowed_extensions and file_extension in allowed_extensions:
                                            # Check if already synced
                                            existing_log = self.env['cloud_storage.sync.log'].search([
                                                ('model_name', '=', model_name),
                                                ('record_id', '=', record.id),
                                                ('file_name', '=', attachment_field.name),
                                                ('status', '=', 'success')
                                            ], limit=1)
                                            
                                            if not existing_log:
                                                files_to_sync.append({
                                                    'record': record,
                                                    'attachment': attachment_field,
                                                    'model_config': model_config,
                                                    'file_extension': file_extension
                                                })
                                                
                    except Exception as e:
                        _logger.error(f"Error processing record {record.id} in model {model_config.model_name}: {str(e)}")
                        continue
                
                offset += batch_size
                
        except Exception as e:
            _logger.error(f"Error getting files for model {model_config.model_name}: {str(e)}")
        
        return files_to_sync

    def _get_or_create_sync_session(self, config):
        """Get or create a sync session for tracking progress"""
        # Check if there's an ongoing session
        existing_session = self.env['cloud_storage.sync.log'].search([
            ('config_id', '=', config.id),
            ('sync_type', '=', 'complete_batch'),
            ('status', '=', 'in_progress')
        ], limit=1)
        
        if existing_session:
            _logger.info(f"[COMPLETE_SYNC] Resuming existing sync session {existing_session.id}")
            return existing_session
        
        # Create new session
        session = self.env['cloud_storage.sync.log'].create({
            'sync_type': 'complete_batch',
            'status': 'in_progress',
            'config_id': config.id,
            'model_name': 'batch_sync',
            'file_name': f'Complete Sync Session - {fields.Datetime.now()}',
            'start_time': fields.Datetime.now(),
            'total_success': 0,
            'total_errors': 0,
            'total_processed': 0
        })
        
        _logger.info(f"[COMPLETE_SYNC] Created new sync session {session.id}")
        return session

    def _count_pending_files(self, model_config, allowed_extensions):
        """Efficiently count files that need to be synced"""
        try:
            model_name = model_config.model_name
            if model_name not in self.env:
                return 0
            
            # Build efficient domain for counting
            if model_name == 'ir.attachment':
                # Count attachments that match criteria and haven't been synced
                domain = [
                    ('res_model', '!=', False),
                    ('type', '=', 'binary'),
                    ('file_size', '>', 0),
                    ('file_size', '<=', 100 * 1024 * 1024),  # 100MB limit
                    ('cloud_sync_status', 'in', ['local', 'error']),  # Not synced yet
                    ('name', '!=', False),  # Not null
                    ('name', '!=', ''),     # Not empty
                    ('name', 'like', '%.%')  # Must contain a dot
                ]
                
                # Add extension filter
                extension_domains = []
                for ext in allowed_extensions:
                    extension_domains.append(('name', 'ilike', f'%.{ext}'))
                
                if extension_domains:
                    if len(extension_domains) > 1:
                        domain.append('|' * (len(extension_domains) - 1))
                    domain.extend(extension_domains)
                
                return self.env['ir.attachment'].search_count(domain)
            
            elif model_name in ['account.move', 'account.invoice', 'purchase.order', 'sale.order']:
                # Count attachments belonging to this model
                attachment_domain = [
                    ('res_model', '=', model_name),
                    ('type', '=', 'binary'),
                    ('file_size', '>', 0),
                    ('file_size', '<=', 100 * 1024 * 1024),
                    ('cloud_sync_status', 'in', ['local', 'error']),
                    ('name', '!=', False),  # Not null
                    ('name', '!=', ''),     # Not empty
                    ('name', 'like', '%.%')  # Must contain a dot
                ]
                
                # Add extension filter
                extension_domains = []
                for ext in allowed_extensions:
                    extension_domains.append(('name', 'ilike', f'%.{ext}'))
                
                if extension_domains:
                    if len(extension_domains) > 1:
                        attachment_domain.append('|' * (len(extension_domains) - 1))
                    attachment_domain.extend(extension_domains)
                
                return self.env['ir.attachment'].search_count(attachment_domain)
            
            elif model_name in ['res.partner', 'hr.employee']:
                # Count records with image fields
                base_domain = []
                if model_name == 'res.partner':
                    base_domain = [
                        '|', ('is_company', '=', True), ('customer_rank', '>', 0),
                        ('image_1920', '!=', False)
                    ]
                elif model_name == 'hr.employee':
                    base_domain = [('image_1920', '!=', False)]
                
                # Check if jpg is in allowed extensions for images
                if 'jpg' not in allowed_extensions:
                    return 0
                
                return self.env[model_name].search_count(base_domain)
            
            return 0
            
        except Exception as e:
            _logger.error(f"Error counting pending files for {model_config.model_name}: {str(e)}")
            return 0

    def _get_batch_files_to_sync(self, model_config, allowed_extensions, batch_size, offset):
        """Get a batch of files to sync with efficient filtering"""
        try:
            model_name = model_config.model_name
            if model_name not in self.env:
                return []
            
            files_to_sync = []
            
            if model_name == 'ir.attachment':
                # Efficient query for attachments
                domain = [
                    ('res_model', '!=', False),
                    ('type', '=', 'binary'),
                    ('file_size', '>', 0),
                    ('file_size', '<=', 100 * 1024 * 1024),
                    ('cloud_sync_status', 'in', ['local', 'error']),
                    ('name', '!=', False),  # Not null
                    ('name', '!=', ''),     # Not empty
                    ('name', 'like', '%.%')  # Must contain a dot
                ]
                
                # Add extension filter
                extension_domains = []
                for ext in allowed_extensions:
                    extension_domains.append(('name', 'ilike', f'%.{ext}'))
                
                if extension_domains:
                    if len(extension_domains) > 1:
                        domain.append('|' * (len(extension_domains) - 1))
                    domain.extend(extension_domains)
                
                attachments = self.env['ir.attachment'].search(
                    domain, 
                    limit=batch_size, 
                    offset=offset,
                    order='id ASC'  # Consistent ordering
                )
                
                for attachment in attachments:
                    try:
                        # Safe extension extraction
                        if attachment.name and '.' in attachment.name:
                            file_extension = attachment.name.split('.')[-1].lower()
                        else:
                            _logger.debug(f"Skipping attachment {attachment.id}: no valid file extension in name '{attachment.name}'")
                            continue
                            
                        if file_extension and file_extension in allowed_extensions:
                            files_to_sync.append({
                                'record': attachment,
                                'attachment': attachment,
                                'model_config': model_config,
                                'file_extension': file_extension
                            })
                        else:
                            _logger.debug(f"Skipping attachment {attachment.id}: extension '{file_extension}' not in allowed extensions")
                    except Exception as e:
                        _logger.error(f"Error processing attachment {attachment.id} in batch: {str(e)}")
                        continue
            
            elif model_name in ['account.move', 'account.invoice', 'purchase.order', 'sale.order']:
                # For document models, look for related attachments instead of field-based files
                # Get attachments that belong to records of this model
                attachment_domain = [
                    ('res_model', '=', model_name),
                    ('type', '=', 'binary'),
                    ('file_size', '>', 0),
                    ('file_size', '<=', 100 * 1024 * 1024),
                    ('cloud_sync_status', 'in', ['local', 'error']),
                    ('name', '!=', False),  # Not null
                    ('name', '!=', ''),     # Not empty
                    ('name', 'like', '%.%')  # Must contain a dot
                ]
                
                # Add extension filter
                extension_domains = []
                for ext in allowed_extensions:
                    extension_domains.append(('name', 'ilike', f'%.{ext}'))
                
                if extension_domains:
                    if len(extension_domains) > 1:
                        attachment_domain.append('|' * (len(extension_domains) - 1))
                    attachment_domain.extend(extension_domains)
                
                attachments = self.env['ir.attachment'].search(
                    attachment_domain,
                    limit=batch_size,
                    offset=offset,
                    order='id ASC'
                )
                
                for attachment in attachments:
                    # Get the related record
                    try:
                        # Skip record existence check for problematic models and process attachment directly
                        if model_name == 'account.move':
                            _logger.debug(f"Processing account.move attachment {attachment.id} without record check due to SQL issues")
                            if attachment.name and '.' in attachment.name:
                                file_extension = attachment.name.split('.')[-1].lower()
                                if file_extension and file_extension in allowed_extensions:
                                    # Use attachment as both record and attachment for compatibility
                                    files_to_sync.append({
                                        'record': attachment,  # Use attachment as record fallback
                                        'attachment': attachment,
                                        'model_config': model_config,
                                        'file_extension': file_extension
                                    })
                                else:
                                    _logger.debug(f"Skipping attachment {attachment.id}: extension '{file_extension}' not in allowed extensions")
                            else:
                                _logger.debug(f"Skipping attachment {attachment.id}: no valid file extension in name '{attachment.name}'")
                        else:
                            # For other models, try normal record check
                            if attachment.res_id:
                                try:
                                    # Use with_context to avoid loading unnecessary fields that might cause SQL errors
                                    record = self.env[model_name].with_context(active_test=False).browse(attachment.res_id)
                                    # Test if record exists without triggering field loading
                                    if record.exists():
                                        # Safe extension extraction
                                        if attachment.name and '.' in attachment.name:
                                            file_extension = attachment.name.split('.')[-1].lower()
                                        else:
                                            _logger.debug(f"Skipping attachment {attachment.id}: no valid file extension in name '{attachment.name}'")
                                            continue
                                            
                                        if file_extension and file_extension in allowed_extensions:
                                            files_to_sync.append({
                                                'record': record,
                                                'attachment': attachment,
                                                'model_config': model_config,
                                                'file_extension': file_extension
                                            })
                                        else:
                                            _logger.debug(f"Skipping attachment {attachment.id}: extension '{file_extension}' not in allowed extensions")
                                    else:
                                        _logger.debug(f"Skipping attachment {attachment.id}: related record {attachment.res_id} doesn't exist in model {model_name}")
                                except Exception as record_error:
                                    _logger.warning(f"Error accessing record {attachment.res_id} in model {model_name}: {str(record_error)}. Using attachment directly.")
                                    # If we can't access the record due to SQL errors, still process the attachment
                                    if attachment.name and '.' in attachment.name:
                                        file_extension = attachment.name.split('.')[-1].lower()
                                        if file_extension and file_extension in allowed_extensions:
                                            # Create a dummy record object for compatibility
                                            files_to_sync.append({
                                                'record': attachment,  # Use attachment as record fallback
                                                'attachment': attachment,
                                                'model_config': model_config,
                                                'file_extension': file_extension
                                            })
                    except Exception as e:
                        _logger.error(f"Error processing attachment {attachment.id} for {model_name} in batch: {str(e)}")
                        continue
            
            elif model_name in ['res.partner', 'hr.employee']:
                # Only process if jpg is allowed
                if 'jpg' in allowed_extensions:
                    base_domain = []
                    if model_name == 'res.partner':
                        base_domain = [
                            '|', ('is_company', '=', True), ('customer_rank', '>', 0),
                            ('image_1920', '!=', False)
                        ]
                    elif model_name == 'hr.employee':
                        base_domain = [('image_1920', '!=', False)]
                    
                    records = self.env[model_name].search(
                        base_domain,
                        limit=batch_size,
                        offset=offset,
                        order='id ASC'
                    )
                    
                    for record in records:
                        if getattr(record, model_config.field_name):
                            file_name = f"{record.display_name or record.name}_{model_config.field_name}.jpg"
                            files_to_sync.append({
                                'record': record,
                                'attachment': self._create_virtual_attachment(record, model_config.field_name, file_name),
                                'model_config': model_config,
                                'file_extension': 'jpg'
                            })
            
            return files_to_sync
            
        except Exception as e:
            _logger.error(f"Error getting batch files for {model_config.model_name}: {str(e)}")
            return []

    def _process_sync_batch(self, batch_files, service, config, sync_session):
        """Process a batch of files and return results"""
        batch_success = 0
        batch_errors = 0
        
        for file_info in batch_files:
            try:
                result = self._sync_file(file_info, service, config)
                
                if result['status'] == 'success':
                    batch_success += 1
                else:
                    batch_errors += 1
                    
            except Exception as sync_error:
                _logger.error(f"Error syncing file in batch: {str(sync_error)}")
                batch_errors += 1
        
        return {
            'success': batch_success,
            'errors': batch_errors
        }

    def _update_sync_session_progress(self, sync_session, sync_session_results):
        """Update sync session with batch progress"""
        sync_session.write({
            'total_success': sync_session.total_success + sync_session_results['success'],
            'total_errors': sync_session.total_errors + sync_session_results['errors'],
            'total_processed': sync_session.total_processed + sync_session_results['success'] + sync_session_results['errors'],
            'last_update': fields.Datetime.now()
        })