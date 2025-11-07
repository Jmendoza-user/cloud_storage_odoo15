# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError
import logging
import os
import base64
from datetime import datetime, timedelta
import time
import random

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
            
            # Use the improved token validation from the auth model
            try:
                valid_token = auth_config._get_valid_token()
            except Exception as token_error:
                _logger.error(f"Token validation failed for {auth_config.name}: {str(token_error)}")
                raise UserError(f"Error de autenticación: {str(token_error)}")
            
            credentials = Credentials(
                token=valid_token,
                refresh_token=auth_config.refresh_token,
                client_id=auth_config.client_id,
                client_secret=auth_config.client_secret,
                token_uri='https://accounts.google.com/o/oauth2/token'
            )
            
            # Build service (disable discovery cache to avoid oauth2client warning)
            service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
            
            # Test the service with a simple API call to verify credentials
            try:
                # Make a simple API call to test the connection
                service.about().get(fields='user').execute()
                _logger.info(f"Successfully connected to Google Drive for {auth_config.name}")
            except Exception as api_error:
                _logger.error(f"API test failed for {auth_config.name}: {str(api_error)}")
                # Try to refresh token and retry
                if auth_config.refresh_access_token():
                    _logger.info(f"Token refreshed, retrying API call for {auth_config.name}")
                    # Update credentials with new token
                    credentials = Credentials(
                        token=auth_config.access_token,
                        refresh_token=auth_config.refresh_token,
                        client_id=auth_config.client_id,
                        client_secret=auth_config.client_secret,
                        token_uri='https://accounts.google.com/o/oauth2/token'
                    )
                    service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
                    # Test again
                    service.about().get(fields='user').execute()
                else:
                    raise UserError("Failed to refresh access token and establish connection")
            
            return service
            
        except Exception as e:
            _logger.error(f"Error creating Google Drive service for {auth_config.name}: {str(e)}")
            raise UserError(f"Error connecting to Google Drive: {str(e)}")

    def _execute_with_backoff(self, func, *, max_retries: int = 5, base_delay: float = 0.5, retriable_statuses=None):
        """Ejecuta una función con reintentos y backoff exponencial + jitter.
        Si la excepción tiene status HTTP 429 o 5xx (configurable), reintenta.
        """
        if retriable_statuses is None:
            retriable_statuses = {429, 500, 502, 503, 504}
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                return func()
            except Exception as exc:  # googleapiclient.errors.HttpError o requests.HTTPError
                last_exc = exc
                status_code = None
                try:
                    # HttpError de googleapiclient
                    if hasattr(exc, 'resp') and hasattr(exc.resp, 'status'):
                        status_code = int(exc.resp.status)
                    # requests
                    elif hasattr(exc, 'response') and exc.response is not None:
                        status_code = int(exc.response.status_code)
                except Exception:
                    status_code = None

                if status_code in retriable_statuses and attempt < max_retries:
                    sleep_s = base_delay * (2 ** attempt) + random.uniform(0, 0.3)
                    _logger.warning(f"[BACKOFF] Intento {attempt+1}/{max_retries} tras error {status_code}. Durmiendo {sleep_s:.2f}s")
                    time.sleep(sleep_s)
                    continue
                else:
                    raise
        # Si sale del bucle sin retorno, relanzar última excepción
        if last_exc:
            raise last_exc

    def _download_drive_file_with_backoff(self, service, file_id: str) -> bytes:
        """Descarga el archivo completo desde Drive usando MediaIoBaseDownload con reintentos."""
        from googleapiclient.http import MediaIoBaseDownload
        import io
        def _do_download():
            request_drive = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request_drive)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            return fh.getvalue()
        return self._execute_with_backoff(_do_download)

    def _http_get_drive_range(self, access_token: str, file_id: str, range_header: str):
        """Hace GET directo a Drive con Range y token Bearer, con backoff. Devuelve (status_code, headers, content_bytes)."""
        import requests
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        if range_header:
            headers['Range'] = range_header
        def _do_get():
            resp = requests.get(url, headers=headers, timeout=30)
            # Considerar 206/200 como válidos; otros pueden lanzar para reintento
            if resp.status_code in (200, 206):
                return resp.status_code, resp.headers, resp.content
            # Levantar HTTPError para que backoff lo maneje
            resp.raise_for_status()
        return self._execute_with_backoff(_do_get)

    # --------------------------
    # Utilidades de listado Drive
    # --------------------------
    def _list_drive_files_in_folder(self, service, folder_id: str, recursive: bool = False, page_size: int = 200):
        """Lista archivos (no carpetas) dentro de una carpeta Drive. Si recursive=True, recorre subcarpetas."""
        files = []
        folders_to_visit = [folder_id]
        while folders_to_visit:
            current = folders_to_visit.pop(0)
            page_token = None
            query = f"'{current}' in parents and trashed=false"
            while True:
                result = service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, mimeType, size, md5Checksum)',
                    pageSize=page_size,
                    pageToken=page_token
                ).execute()
                for f in result.get('files', []):
                    if f.get('mimeType') == 'application/vnd.google-apps.folder':
                        if recursive:
                            folders_to_visit.append(f['id'])
                    else:
                        files.append(f)
                page_token = result.get('nextPageToken')
                if not page_token:
                    break
        return files

    # --------------------------
    # Previews (conteo/impacto)
    # --------------------------
    def preview_migration(self, source_auth_id: int, only_folder_id: str = None,
                          recursive: bool = True, limit: int = 0):
        """Devuelve {'count': int, 'total_size': int, 'sample': [str]} para migración desde cuenta origen."""
        source_auth = self.env['cloud_storage.auth'].sudo().browse(source_auth_id)
        if not source_auth.exists() or source_auth.state != 'authorized':
            raise UserError('Autenticación de origen inválida o no autorizada')
        service = self._get_google_drive_service(source_auth)
        files = []
        if only_folder_id:
            files = self._list_drive_files_in_folder(service, only_folder_id, recursive=recursive)
            if limit and limit > 0:
                files = files[:limit]
        else:
            # Basado en ir.attachment sincronizados, validar existencia y tamaños
            domain = [('cloud_sync_status', '=', 'synced'), ('cloud_file_id', '!=', False)]
            attachments = self.env['ir.attachment'].sudo().search(domain, limit=(limit or 1000))
            for att in attachments:
                try:
                    meta = service.files().get(fileId=att.cloud_file_id, fields='id, name, size').execute()
                    if meta:
                        files.append(meta)
                except Exception:
                    continue
        count = len(files)
        total_size = 0
        sample = []
        for f in files:
            try:
                total_size += int(f.get('size') or 0)
                if len(sample) < 10:
                    sample.append(f.get('name'))
            except Exception:
                continue
        return {'count': count, 'total_size': total_size, 'sample': sample}

    def preview_restore(self, auth_id: int, folder_id: str, recursive: bool = True, limit: int = 0):
        """Devuelve {'count': int, 'total_size': int, 'sample': [str]} para restauración local desde carpeta."""
        auth = self.env['cloud_storage.auth'].sudo().browse(auth_id)
        if not auth.exists() or auth.state != 'authorized':
            raise UserError('Autenticación inválida o no autorizada')
        service = self._get_google_drive_service(auth)
        files = self._list_drive_files_in_folder(service, folder_id, recursive=recursive)
        if limit and limit > 0:
            files = files[:limit]
        count = len(files)
        total_size = 0
        sample = []
        for f in files:
            try:
                total_size += int(f.get('size') or 0)
                if len(sample) < 10:
                    sample.append(f.get('name'))
            except Exception:
                continue
        return {'count': count, 'total_size': total_size, 'sample': sample}

    # --------------------------
    # Migración entre cuentas Drive
    # --------------------------
    def migrate_attachments_between_auth(self, source_auth_id: int, target_auth_id: int,
                                         only_folder_id: str = None, target_folder_id: str = None,
                                         recursive: bool = True, limit: int = 0,
                                         verify_integrity: bool = True,
                                         delete_source: bool = False,
                                         delete_mode: str = 'trash'):
        """Migra archivos de Drive de una cuenta (source_auth_id) a otra (target_auth_id).
        - Si only_folder_id está definido, solo migra los archivos de esa carpeta en origen.
        - Si target_folder_id está definido, sube los archivos a esa carpeta en destino.
        - Si limit>0, migra como máximo ese número de archivos.
        Actualiza los `ir.attachment` correspondientes (por `cloud_file_id`).
        """
        source_auth = self.env['cloud_storage.auth'].sudo().browse(source_auth_id)
        target_auth = self.env['cloud_storage.auth'].sudo().browse(target_auth_id)
        if not source_auth.exists() or not target_auth.exists():
            raise UserError('Autenticaciones de origen o destino inválidas')
        source_service = self._get_google_drive_service(source_auth)
        target_service = self._get_google_drive_service(target_auth)

        # Determinar lista de archivos a migrar
        files_to_migrate = []
        if only_folder_id:
            files_to_migrate = self._list_drive_files_in_folder(source_service, only_folder_id, recursive=recursive)
        else:
            # Fallback: usar adjuntos registrados
            atts_domain = [('cloud_sync_status', '=', 'synced'), ('cloud_file_id', '!=', False)]
            if limit and limit > 0:
                attachments = self.env['ir.attachment'].sudo().search(atts_domain, limit=limit)
            else:
                attachments = self.env['ir.attachment'].sudo().search(atts_domain)
            # Validar que el archivo existe en origen
            for att in attachments:
                try:
                    meta = source_service.files().get(fileId=att.cloud_file_id, fields='id, name, mimeType, size, md5Checksum').execute()
                    if meta:
                        files_to_migrate.append(meta)
                except Exception:
                    continue

        migrated = 0
        for f in files_to_migrate:
            try:
                file_id = f['id']
                # Encontrar attachment correspondiente por cloud_file_id
                attachment = self.env['ir.attachment'].sudo().search([('cloud_file_id', '=', file_id)], limit=1)
                if not attachment:
                    # Si no existe en Odoo, omitir para no generar huérfanos
                    continue
                # Descargar del origen con backoff
                content_bytes = self._download_drive_file_with_backoff(source_service, file_id)
                import hashlib
                try:
                    source_size = int(f.get('size')) if f.get('size') else len(content_bytes)
                except Exception:
                    source_size = len(content_bytes)
                try:
                    source_md5 = f.get('md5Checksum') or hashlib.md5(content_bytes).hexdigest()
                except Exception:
                    source_md5 = hashlib.md5(content_bytes).hexdigest()
                # Subir a destino
                upload_folder = target_folder_id
                drive_file = self._upload_file_to_drive(target_service, content_bytes, attachment.name, upload_folder)

                # Actualizar attachment a nuevo file id y metadatos
                update_vals = {
                    'cloud_file_id': drive_file.get('id'),
                    'cloud_storage_url': drive_file.get('web_view_link'),
                    'cloud_md5': drive_file.get('md5'),
                    'cloud_size_bytes': drive_file.get('size'),
                    'cloud_synced_date': fields.Datetime.now(),
                    'cloud_sync_status': 'synced',
                    'cloud_auth_id': target_auth.id,
                }
                attachment.write(update_vals)

                # Verificación post-migración
                if verify_integrity:
                    dest_md5 = drive_file.get('md5')
                    dest_size = drive_file.get('size')
                    if (dest_md5 and source_md5 and dest_md5 != source_md5) or (dest_size and source_size and int(dest_size) != int(source_size)):
                        _logger.error(f"[MIGRATION] Verificación fallida para attachment {attachment.id}: src(md5={source_md5}, size={source_size}) vs dst(md5={dest_md5}, size={dest_size})")
                        # No borrar en origen si la verificación falla
                        migrated += 1
                        time.sleep(0.05)
                        if limit and migrated >= limit:
                            break
                        continue

                # Eliminar en origen si se solicita
                if delete_source:
                    def _trash():
                        body = {'trashed': True}
                        return source_service.files().update(fileId=file_id, body=body, fields='id, trashed').execute()
                    def _delete():
                        return source_service.files().delete(fileId=file_id).execute()
                    try:
                        if delete_mode == 'delete':
                            self._execute_with_backoff(_delete)
                        else:
                            self._execute_with_backoff(_trash)
                    except Exception as del_err:
                        _logger.warning(f"[MIGRATION] No se pudo eliminar/mover a papelera el archivo origen {file_id}: {del_err}")
                migrated += 1
                # Pequeña pausa para respetar cuotas
                time.sleep(0.05)
                if limit and migrated >= limit:
                    break
            except Exception as e:
                _logger.error(f"[MIGRATION] Error migrando archivo {f.get('id')}: {e}")
                continue
        return migrated

    # --------------------------
    # Restauración local desde carpeta de Drive
    # --------------------------
    def restore_local_from_drive_folder(self, auth_id: int, folder_id: str, *, recursive: bool = True,
                                        link_existing: bool = True, default_res_model: str = None,
                                        default_res_id: int = None, limit: int = 0):
        """Restaura localmente archivos de una carpeta de Drive:
        - Si existe un `ir.attachment` con `cloud_file_id` igual al del archivo, repone `datas` local.
        - Si no existe y se especifican `default_res_model` y `default_res_id`, crea un `ir.attachment` nuevo.
        - `recursive=True` recorrerá subcarpetas.
        - `limit` limita el número de archivos procesados.
        """
        auth = self.env['cloud_storage.auth'].sudo().browse(auth_id)
        if not auth.exists() or auth.state != 'authorized':
            raise UserError('Autenticación inválida o no autorizada')
        service = self._get_google_drive_service(auth)
        files = self._list_drive_files_in_folder(service, folder_id, recursive=recursive)
        restored = 0
        import base64
        for f in files:
            try:
                file_id = f['id']
                name = f.get('name')
                mimetype = f.get('mimeType') or 'application/octet-stream'
                content_bytes = self._download_drive_file_with_backoff(service, file_id)
                b64 = base64.b64encode(content_bytes)
                attachment = None
                if link_existing:
                    attachment = self.env['ir.attachment'].sudo().search([('cloud_file_id', '=', file_id)], limit=1)
                if attachment:
                    attachment.write({
                        'type': 'binary',
                        'datas': b64,
                        'mimetype': mimetype,
                    })
                else:
                    vals = {
                        'name': name,
                        'type': 'binary',
                        'datas': b64,
                        'mimetype': mimetype,
                        'cloud_file_id': file_id,
                        'cloud_storage_url': None,
                        'cloud_sync_status': 'synced',
                    }
                    if default_res_model and default_res_id:
                        vals.update({'res_model': default_res_model, 'res_id': default_res_id})
                    self.env['ir.attachment'].sudo().create(vals)
                restored += 1
                if limit and restored >= limit:
                    break
            except Exception as e:
                _logger.error(f"[RESTORE] Error restaurando archivo {f.get('id')}: {e}")
                continue
        return restored

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
                'original_local_path': original_local_path,
                'cloud_md5': drive_file.get('md5'),
                'cloud_size_bytes': drive_file.get('size'),
                'cloud_auth_id': config.auth_id.id if config and config.auth_id else False
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
            
            # Verificar integridad antes de borrar local
            if config.delete_local_after_sync:
                try:
                    import hashlib
                    # Calcular MD5 local si hay contenido
                    local_md5 = None
                    if original_file_content:
                        local_md5 = hashlib.md5(original_file_content).hexdigest()
                    cloud_md5 = drive_file.get('md5')
                    # Si se dispone de ambos, validar
                    if cloud_md5 and local_md5 and cloud_md5 != local_md5:
                        _logger.error(f"MD5 mismatch for attachment {attachment.name}: local={local_md5}, cloud={cloud_md5}")
                        # No borrar local, marcar error
                        attachment.write({'cloud_sync_status': 'error'})
                    else:
                        self._delete_local_file(attachment)
                except Exception as integ_err:
                    _logger.error(f"Integrity check failed for {attachment.name}: {integ_err}")
                    attachment.write({'cloud_sync_status': 'error'})
            
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
            # Si se recibe parent_id, buscar por nombre dentro de ese padre
            if parent_id:
                q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false and '{parent_id}' in parents"
            else:
                q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            existing = service.files().list(q=q, fields='files(id, name, parents)').execute()
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
                fields='id,webViewLink,webContentLink,md5Checksum,size'
            ).execute()
            
            return {
                'id': file.get('id'),
                'web_view_link': file.get('webViewLink'),
                'web_content_link': file.get('webContentLink'),
                'md5': file.get('md5Checksum'),
                'size': int(file.get('size')) if file.get('size') else None
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

                # Universal approach: always search in ir.attachment filtered by res_model
                # This works for ANY model the user configures
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
                            # Add OR operators as separate list items
                            for _ in range(len(extension_domains) - 1):
                                attachment_domain.append('|')
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

                # Process all attachments found for this model
                for i, attachment in enumerate(attachments):
                    _logger.debug(f"[MANUAL_SYNC] Processing attachment {i+1}/{len(attachments)} for {model_name}: ID={attachment.id}, name='{attachment.name}'")
                    try:
                        # Safe extension extraction
                        if attachment.name and '.' in attachment.name:
                            file_extension = attachment.name.split('.')[-1].lower()
                        else:
                            _logger.debug(f"Skipping attachment {attachment.id}: no valid file extension in name '{attachment.name}'")
                            continue

                        if file_extension and file_extension in allowed_extensions:
                            # Use attachment directly - no need to check if record exists
                            files_to_sync.append({
                                'record': attachment,
                                'attachment': attachment,
                                'model_config': model_config,
                                'file_extension': file_extension
                            })
                        else:
                            _logger.debug(f"Skipping attachment {attachment.id}: extension '{file_extension}' not in allowed extensions")
                    except Exception as e:
                        _logger.error(f"Error processing attachment {attachment.id} for {model_name}: {str(e)}")
                        continue

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
            try:
                config = self.env['cloud_storage.config'].get_active_config()
            except Exception:
                config = None
            root_parent = config.drive_root_folder_id if config and config.drive_root_folder_id else None
            if model_config.drive_folder_name:
                folder_id = self._create_drive_folder(service, model_config.drive_folder_name, parent_id=root_parent)
            
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

    @api.model
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
    def manual_sync_safe(self):
        """
        Safe wrapper for manual_sync that handles all exceptions gracefully.
        Used by server actions to prevent migration test failures.
        """
        try:
            return self.manual_sync()
        except UserError as e:
            _logger.warning(f"cloud_storage: manual_sync UserError (expected during migration): {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Sync not available: {str(e)}",
                    'type': 'warning'
                }
            }
        except Exception as e:
            _logger.error(f"cloud_storage: manual_sync unexpected error: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Error during sync: {str(e)}",
                    'type': 'danger'
                }
            }

    @api.model
    def automatic_sync(self, batch_limit=100):
        """Automatic sync via cron - processes files in batches and creates summary logs"""
        _logger.info("[AUTO_SYNC] Starting automatic synchronization")

        configs = self.env['cloud_storage.config'].search([
            ('is_active', '=', True),
            ('auto_sync', '=', True)
        ])

        if not configs:
            _logger.info("[AUTO_SYNC] No active configurations with auto_sync enabled")
            return True

        for config in configs:
            sync_session = None
            try:
                # Validate authentication
                if not config.auth_id or config.auth_id.state != 'authorized':
                    error_msg = f"Authentication not valid for config {config.name}"
                    _logger.warning(f"[AUTO_SYNC] {error_msg}")

                    # Create error log
                    self.env['cloud_storage.sync.log'].create({
                        'sync_type': 'automatic',
                        'status': 'error',
                        'config_id': config.id,
                        'model_name': 'auto_sync_session',
                        'file_name': f'Auto Sync Session - {fields.Datetime.now()}',
                        'error_message': error_msg,
                        'start_time': fields.Datetime.now()
                    })
                    continue

                # Get allowed extensions
                allowed_extensions = config.file_type_ids.filtered('is_active').mapped('extension')
                if not allowed_extensions:
                    error_msg = "No active file types configured"
                    _logger.warning(f"[AUTO_SYNC] {error_msg} for config {config.name}")

                    self.env['cloud_storage.sync.log'].create({
                        'sync_type': 'automatic',
                        'status': 'error',
                        'config_id': config.id,
                        'model_name': 'auto_sync_session',
                        'file_name': f'Auto Sync Session - {fields.Datetime.now()}',
                        'error_message': error_msg,
                        'start_time': fields.Datetime.now()
                    })
                    continue

                _logger.info(f"[AUTO_SYNC] Processing config {config.name} with extensions: {allowed_extensions}")

                # Create sync session for tracking
                sync_session = self.env['cloud_storage.sync.log'].create({
                    'sync_type': 'automatic',
                    'status': 'in_progress',
                    'config_id': config.id,
                    'model_name': 'auto_sync_session',
                    'file_name': f'Auto Sync Session - {fields.Datetime.now()}',
                    'start_time': fields.Datetime.now(),
                    'total_success': 0,
                    'total_errors': 0,
                    'total_processed': 0
                })

                service = self._get_google_drive_service(config.auth_id)

                total_processed = 0
                total_success = 0
                total_errors = 0

                # Process each active model configuration
                for model_config in config.model_config_ids.filtered('is_active'):
                    try:
                        model_name = model_config.model_name

                        if model_name not in self.env:
                            _logger.warning(f"[AUTO_SYNC] Model {model_name} does not exist. Skipping.")
                            continue

                        # Count pending files
                        pending_count = self._count_pending_files(model_config, allowed_extensions)
                        _logger.info(f"[AUTO_SYNC] Found {pending_count} pending files for {model_name}")

                        if pending_count == 0:
                            continue

                        # Limit files per model to avoid long-running cron
                        files_to_process = min(pending_count, batch_limit)

                        # Get batch of files
                        batch_files = self._get_batch_files_to_sync(
                            model_config, allowed_extensions, files_to_process, 0
                        )

                        if not batch_files:
                            continue

                        _logger.info(f"[AUTO_SYNC] Processing {len(batch_files)} files for {model_name}")

                        # Process files
                        for file_info in batch_files:
                            try:
                                result = self._sync_file_automatic(file_info, service, config, model_config)

                                total_processed += 1
                                if result['status'] == 'success':
                                    total_success += 1
                                    _logger.info(f"[AUTO_SYNC] Success: {result['file_name']}")
                                else:
                                    total_errors += 1
                                    _logger.error(f"[AUTO_SYNC] Error: {result['file_name']} - {result.get('message', 'Unknown error')}")

                            except Exception as file_error:
                                total_errors += 1
                                total_processed += 1
                                _logger.error(f"[AUTO_SYNC] Exception syncing file: {str(file_error)}")
                                continue

                        # Commit after each model to save progress
                        self.env.cr.commit()

                    except Exception as model_error:
                        _logger.error(f"[AUTO_SYNC] Error processing model {model_config.model_name}: {str(model_error)}")
                        continue

                # Mark session as completed
                if sync_session:
                    sync_session.write({
                        'status': 'completed',
                        'end_time': fields.Datetime.now(),
                        'total_success': total_success,
                        'total_errors': total_errors,
                        'total_processed': total_processed
                    })

                _logger.info(f"[AUTO_SYNC] Completed for config {config.name}. Success: {total_success}, Errors: {total_errors}, Total: {total_processed}")

            except Exception as config_error:
                error_msg = str(config_error)
                _logger.error(f"[AUTO_SYNC] Error processing config {config.name}: {error_msg}")

                # Mark session as error if it exists
                if sync_session:
                    sync_session.write({
                        'status': 'error',
                        'end_time': fields.Datetime.now(),
                        'error_message': error_msg
                    })

                continue

        _logger.info("[AUTO_SYNC] Automatic synchronization completed")
        return True

    def _sync_file_automatic(self, file_info, service, config, model_config):
        """Sync a single file for automatic sync - similar to _sync_file but with automatic sync_type"""
        try:
            attachment = file_info['attachment']
            record = file_info['record']

            if not attachment.datas:
                error_msg = 'No file data available'
                _logger.warning(f"[AUTO_SYNC] {error_msg} for {attachment.name}")

                # Create error log
                self.env['cloud_storage.sync.log'].create({
                    'sync_type': 'automatic',
                    'status': 'error',
                    'model_name': model_config.model_name,
                    'record_id': record.id if hasattr(record, 'id') else False,
                    'file_name': attachment.name,
                    'error_message': error_msg,
                    'config_id': config.id
                })

                return {
                    'status': 'error',
                    'message': error_msg,
                    'file_name': attachment.name
                }

            # Check file size
            file_size = attachment.file_size or 0
            max_file_size = 100 * 1024 * 1024  # 100MB

            if file_size > max_file_size:
                error_msg = f'File too large ({file_size / (1024*1024):.1f}MB). Maximum: 100MB'
                _logger.warning(f"[AUTO_SYNC] {error_msg}: {attachment.name}")

                self.env['cloud_storage.sync.log'].create({
                    'sync_type': 'automatic',
                    'status': 'error',
                    'model_name': model_config.model_name,
                    'record_id': record.id if hasattr(record, 'id') else False,
                    'file_name': attachment.name,
                    'error_message': error_msg,
                    'config_id': config.id
                })

                return {
                    'status': 'error',
                    'message': error_msg,
                    'file_name': attachment.name
                }

            # Decode file content
            try:
                file_content = base64.b64decode(attachment.datas)
            except Exception as decode_error:
                error_msg = f'Error decoding file data: {str(decode_error)}'
                _logger.error(f"[AUTO_SYNC] {error_msg}")

                self.env['cloud_storage.sync.log'].create({
                    'sync_type': 'automatic',
                    'status': 'error',
                    'model_name': model_config.model_name,
                    'record_id': record.id if hasattr(record, 'id') else False,
                    'file_name': attachment.name,
                    'error_message': error_msg,
                    'config_id': config.id
                })

                return {
                    'status': 'error',
                    'message': error_msg,
                    'file_name': attachment.name
                }

            # Create folder if needed
            folder_id = None
            root_parent = config.drive_root_folder_id if config.drive_root_folder_id else None
            if model_config.drive_folder_name:
                folder_id = self._create_drive_folder(service, model_config.drive_folder_name, parent_id=root_parent)

            # Upload to Drive
            drive_file = self._upload_file_to_drive(
                service, file_content, attachment.name, folder_id
            )

            # Update attachment if configured
            if config.replace_local_with_cloud:
                self._update_attachment_to_cloud(attachment, drive_file, file_content, config)

            # Create success log
            sync_log = self.env['cloud_storage.sync.log'].create({
                'sync_type': 'automatic',
                'status': 'success',
                'model_name': model_config.model_name,
                'record_id': record.id if hasattr(record, 'id') else False,
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
            _logger.error(f"[AUTO_SYNC] Error syncing file {attachment.name}: {error_msg}")

            # Create error log
            self.env['cloud_storage.sync.log'].create({
                'sync_type': 'automatic',
                'status': 'error',
                'model_name': model_config.model_name,
                'record_id': record.id if hasattr(record, 'id') else False,
                'file_name': attachment.name,
                'error_message': error_msg,
                'config_id': config.id
            })

            return {
                'status': 'error',
                'file_name': attachment.name,
                'message': error_msg
            }

    @api.model
    def reconcile_cloud_references(self, limit=200):
        """Verifica referencias en Drive y repara metadatos básicos"""
        _logger.info(f"[RECONCILE] Iniciando reconciliación de hasta {limit} adjuntos")
        config = self.env['cloud_storage.config'].sudo().get_active_config()
        if not config or not config.auth_id or config.auth_id.state != 'authorized':
            _logger.warning("[RECONCILE] No hay configuración activa/autorizada")
            return 0
        service = self._get_google_drive_service(config.auth_id)
        count_ok = 0
        attachments = self.env['ir.attachment'].search([
            ('cloud_sync_status', 'in', ['synced', 'error']),
            ('cloud_file_id', '!=', False)
        ], limit=limit, order='id desc')
        for att in attachments:
            try:
                meta = service.files().get(fileId=att.cloud_file_id, fields='id,md5Checksum,size,trashed').execute()
                if not meta or meta.get('trashed'):
                    _logger.warning(f"[RECONCILE] Archivo faltante/trashed en Drive para attachment {att.id}")
                    att.write({'cloud_sync_status': 'error'})
                    continue
                updates = {}
                md5 = meta.get('md5Checksum')
                size = int(meta.get('size')) if meta.get('size') else None
                if md5 and att.cloud_md5 != md5:
                    updates['cloud_md5'] = md5
                if size and att.cloud_size_bytes != size:
                    updates['cloud_size_bytes'] = size
                if updates:
                    att.write(updates)
                count_ok += 1
            except Exception as e:
                _logger.warning(f"[RECONCILE] Error verificando attachment {att.id}: {e}")
                att.write({'cloud_sync_status': 'error'})
                continue
        _logger.info(f"[RECONCILE] Finalizado. Verificados OK: {count_ok}")
        return count_ok

    @api.model
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

            # Universal approach: count attachments filtered by res_model
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
                    # Add OR operators as separate list items
                    for _ in range(len(extension_domains) - 1):
                        attachment_domain.append('|')
                attachment_domain.extend(extension_domains)

            return self.env['ir.attachment'].search_count(attachment_domain)

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

            # Universal approach: always search in ir.attachment filtered by res_model
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
                    # Add OR operators as separate list items
                    for _ in range(len(extension_domains) - 1):
                        attachment_domain.append('|')
                attachment_domain.extend(extension_domains)

            attachments = self.env['ir.attachment'].search(
                attachment_domain,
                limit=batch_size,
                offset=offset,
                order='id ASC'
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
