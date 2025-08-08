# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import json
import logging
import requests
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class CloudStorageAuth(models.Model):
    _name = 'cloud_storage.auth'
    _description = 'Google Drive Authentication'
    _rec_name = 'name'

    name = fields.Char('Configuration Name', required=True)
    client_id = fields.Char('Google Client ID', required=True)
    client_secret = fields.Char('Google Client Secret', required=True)
    redirect_uri = fields.Char('Redirect URI', default='http://10.10.6.222:8089/cloud_storage/oauth/callback', 
                              help="Custom redirect URI for OAuth callback")
    access_token = fields.Text('Access Token')
    refresh_token = fields.Text('Refresh Token')
    token_expiry = fields.Datetime('Token Expiry')
    is_active = fields.Boolean('Active', default=True)
    auth_uri = fields.Char('Authorization URI', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Authorization'),
        ('authorized', 'Authorized'),
        ('expired', 'Token Expired'),
        ('error', 'Error')
    ], default='draft', string='Status')

    def get_auth_url(self):
        """Generate OAuth authorization URL using working method"""
        self.ensure_one()
        
        if not self.client_id:
            raise UserError("Client ID is required to generate authorization URL")
        
        # Use custom callback URL or generate from base URL
        callback_url = self.redirect_uri
        if not callback_url:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://10.10.6.222:8089')
            callback_url = f"{base_url}/cloud_storage/oauth/callback"
        
        auth_base_url = 'https://accounts.google.com/o/oauth2/auth'
        params = {
            'client_id': self.client_id,
            'redirect_uri': callback_url,
            'scope': 'https://www.googleapis.com/auth/drive',
            'response_type': 'code',
            'access_type': 'offline',
            'prompt': 'consent',
            'state': f'auth_{self.id}'
        }
        
        auth_url = auth_base_url + '?' + '&'.join([f'{k}={v}' for k, v in params.items()])
        
        self.write({
            'auth_uri': auth_url,
            'state': 'pending'
        })
        
        return auth_url
    
    def action_authorize(self):
        """Action to get and display authorization URL"""
        self.ensure_one()
        
        try:
            auth_url = self.get_auth_url()
            return {
                'type': 'ir.actions.act_url',
                'url': auth_url,
                'target': 'new'
            }
        except Exception as e:
            _logger.error(f"Error during authorization: {str(e)}")
            raise UserError(f"Error durante la autorización: {str(e)}")
    
    def exchange_code_for_token(self, code):
        """Exchange authorization code for access token"""
        self.ensure_one()
        
        try:
            callback_url = self.redirect_uri
            if not callback_url:
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://10.10.6.222:8089')
                callback_url = f"{base_url}/cloud_storage/oauth/callback"
            
            url = 'https://accounts.google.com/o/oauth2/token'
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': callback_url
            }
            
            response = requests.post(url, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            
            self.write({
                'access_token': token_data.get('access_token'),
                'refresh_token': token_data.get('refresh_token'),
                'token_expiry': fields.Datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600)),
                'state': 'authorized'
            })
            
            return True
            
        except Exception as e:
            _logger.error(f'Error exchanging code for token: {str(e)}')
            self.state = 'error'
            return False
    
    def refresh_access_token(self):
        """Refresh access token using refresh token"""
        self.ensure_one()
        
        if not self.refresh_token:
            _logger.error("No refresh token available for token refresh")
            self.state = 'error'
            return False
        
        if not self.client_id or not self.client_secret:
            _logger.error("Client ID or Client Secret missing for token refresh")
            self.state = 'error'
            return False
        
        try:
            url = 'https://accounts.google.com/o/oauth2/token'
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': self.refresh_token,
                'grant_type': 'refresh_token'
            }
            
            _logger.info(f"Attempting to refresh token for auth config: {self.name}")
            response = requests.post(url, data=data, timeout=30)
            
            if response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get('error_description', 'Unknown error')
                _logger.error(f"Token refresh failed with 400 error: {error_msg}")
                
                # Check if refresh token is invalid
                if 'invalid_grant' in error_msg.lower():
                    self.state = 'expired'
                    _logger.warning(f"Refresh token appears to be invalid for {self.name}")
                else:
                    self.state = 'error'
                
                return False
            
            response.raise_for_status()
            
            token_data = response.json()
            
            if not token_data.get('access_token'):
                _logger.error("No access token received in refresh response")
                self.state = 'error'
                return False
            
            # Calculate expiry time
            expires_in = token_data.get('expires_in', 3600)
            expiry_time = fields.Datetime.now() + timedelta(seconds=expires_in)
            
            self.write({
                'access_token': token_data.get('access_token'),
                'token_expiry': expiry_time,
                'state': 'authorized'
            })
            
            _logger.info(f"Successfully refreshed token for {self.name}. New expiry: {expiry_time}")
            return True
            
        except requests.exceptions.Timeout:
            _logger.error(f"Timeout while refreshing token for {self.name}")
            self.state = 'error'
            return False
        except requests.exceptions.RequestException as e:
            _logger.error(f"Network error while refreshing token for {self.name}: {str(e)}")
            self.state = 'error'
            return False
        except Exception as e:
            _logger.error(f'Unexpected error refreshing token for {self.name}: {str(e)}')
            self.state = 'error'
            return False
    
    def _get_valid_token(self):
        """Get valid access token, refreshing if necessary"""
        self.ensure_one()
        
        if not self.access_token:
            raise UserError("No access token available. Please authorize first.")
        
        # Check if token is expired or will expire soon (within 5 minutes)
        now = fields.Datetime.now()
        if self.token_expiry:
            time_until_expiry = self.token_expiry - now
            
            # If token is expired or will expire within 5 minutes, refresh it
            if time_until_expiry.total_seconds() <= 300:  # 5 minutes
                _logger.info(f"Token for {self.name} is expired or expiring soon, attempting refresh")
                if not self.refresh_access_token():
                    raise UserError("Failed to refresh access token")
        
        return self.access_token

    def test_connection(self):
        """Test connection to Google Drive using working method"""
        self.ensure_one()
        
        try:
            token = self._get_valid_token()
            
            url = 'https://www.googleapis.com/drive/v3/about'
            headers = {'Authorization': f'Bearer {token}'}
            params = {'fields': 'user'}
            
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            user_info = data.get('user', {})
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Conexión exitosa. Usuario: {user_info.get('emailAddress', 'N/A')}",
                    'type': 'success'
                }
            }
            
        except Exception as e:
            _logger.error(f"Error testing connection: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Error de conexión: {str(e)}",
                    'type': 'danger'
                }
            }

    def action_refresh_token(self):
        """Action to manually refresh the access token"""
        self.ensure_one()
        
        try:
            if not self.refresh_token:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': "No hay token de refresco disponible. Necesitas reautorizar la conexión.",
                        'type': 'warning'
                    }
                }
            
            if self.refresh_access_token():
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': f"Token refrescado exitosamente. Nuevo vencimiento: {self.token_expiry}",
                        'type': 'success'
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': "Error al refrescar el token. Verifica tu configuración.",
                        'type': 'danger'
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error refreshing token: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Error al refrescar el token: {str(e)}",
                    'type': 'danger'
                }
            }

    def action_check_token_status(self):
        """Check and display current token status"""
        self.ensure_one()
        
        try:
            if not self.access_token:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': "No hay token de acceso configurado.",
                        'type': 'warning'
                    }
                }
            
            if not self.token_expiry:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': "Token de acceso sin fecha de vencimiento configurada.",
                        'type': 'warning'
                    }
                }
            
            now = fields.Datetime.now()
            time_until_expiry = self.token_expiry - now
            
            if time_until_expiry.total_seconds() <= 0:
                status_msg = "Token expirado"
                status_type = "danger"
            elif time_until_expiry.total_seconds() < 3600:  # Less than 1 hour
                status_msg = f"Token expira en {int(time_until_expiry.total_seconds() / 60)} minutos"
                status_type = "warning"
            else:
                hours_remaining = int(time_until_expiry.total_seconds() / 3600)
                status_msg = f"Token válido por {hours_remaining} horas"
                status_type = "success"
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Estado del token: {status_msg}",
                    'type': status_type
                }
            }
            
        except Exception as e:
            _logger.error(f"Error checking token status: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Error al verificar estado del token: {str(e)}",
                    'type': 'danger'
                }
            }


class CloudStorageConfig(models.Model):
    _name = 'cloud_storage.config'
    _description = 'Cloud Storage Configuration'
    _rec_name = 'name'

    name = fields.Char('Configuration Name', required=True)
    auth_id = fields.Many2one('cloud_storage.auth', 'Authentication', required=True)
    is_active = fields.Boolean('Active', default=True)
    auto_sync = fields.Boolean('Auto Sync', default=False, help="Enable automatic synchronization via cron")
    sync_frequency = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly')
    ], default='daily', string='Sync Frequency')
    delete_local_after_sync = fields.Boolean('Delete Local Files After Sync', default=False, 
                                           help="Remove local files after successful sync to cloud storage (saves disk space)")
    replace_local_with_cloud = fields.Boolean('Replace Local with Cloud URLs', default=True,
                                            help="Update file references to point to cloud storage instead of local files")
    
    # Performance optimizations
    enable_cloud_access = fields.Boolean('Enable Cloud Access', default=True,
                                        help="Allow accessing files from cloud (disable for better performance)")
    cache_timeout_minutes = fields.Integer('Cache Timeout (minutes)', default=5,
                                         help="How long to cache downloaded files in memory")
    max_cache_size = fields.Integer('Max Cache Size', default=50,
                                  help="Maximum number of files to keep in memory cache")
    
    model_config_ids = fields.One2many('cloud_storage.model.config', 'config_id', 'Model Configurations')
    file_type_ids = fields.One2many('cloud_storage.file.type', 'config_id', 'File Types')

    @api.model
    def get_active_config(self):
        return self.search([('is_active', '=', True)], limit=1)

    def manual_sync(self):
        self.ensure_one()
        if not self.is_active:
            raise UserError("Configuration is not active")
        
        sync_service = self.env['cloud_storage.sync.service']
        return sync_service.manual_sync()
    
    def complete_sync(self):
        self.ensure_one()
        if not self.is_active:
            raise UserError("Configuration is not active")
        
        sync_service = self.env['cloud_storage.sync.service']
        return sync_service.complete_sync()
    
    def create_default_model_configs(self):
        """Create default model configurations for common Odoo models with attachments"""
        self.ensure_one()
        
        default_configs = [
            {
                'model_name': 'ir.attachment',
                'display_name': 'Attachments',
                'field_name': 'datas',
                'drive_folder_name': 'Attachments'
            },
            {
                'model_name': 'res.partner',
                'display_name': 'Partners/Contacts',  
                'field_name': 'image_1920',
                'drive_folder_name': 'Partner Images'
            },
            {
                'model_name': 'hr.employee',
                'display_name': 'Employees',
                'field_name': 'image_1920', 
                'drive_folder_name': 'Employee Images'
            }
        ]
        
        created_configs = []
        for config_data in default_configs:
            # Check if model exists in this Odoo instance
            if config_data['model_name'] in self.env:
                # Check if config already exists
                existing = self.model_config_ids.filtered(
                    lambda c: c.model_name == config_data['model_name']
                )
                if not existing:
                    model_config = self.env['cloud_storage.model.config'].create({
                        'config_id': self.id,
                        **config_data
                    })
                    created_configs.append(model_config)
        
        return created_configs
    
    def create_default_file_types(self):
        """Create default file type configurations"""
        self.ensure_one()
        
        default_file_types = [
            {'extension': 'pdf', 'description': 'PDF Documents', 'max_size_mb': 50.0},
            {'extension': 'doc', 'description': 'Word Documents', 'max_size_mb': 25.0},
            {'extension': 'docx', 'description': 'Word Documents', 'max_size_mb': 25.0},
            {'extension': 'xls', 'description': 'Excel Files', 'max_size_mb': 25.0},
            {'extension': 'xlsx', 'description': 'Excel Files', 'max_size_mb': 25.0},
            {'extension': 'jpg', 'description': 'JPEG Images', 'max_size_mb': 10.0},
            {'extension': 'jpeg', 'description': 'JPEG Images', 'max_size_mb': 10.0},
            {'extension': 'png', 'description': 'PNG Images', 'max_size_mb': 10.0},
            {'extension': 'txt', 'description': 'Text Files', 'max_size_mb': 5.0},
        ]
        
        created_types = []
        for file_type_data in default_file_types:
            # Check if file type already exists
            existing = self.file_type_ids.filtered(
                lambda ft: ft.extension == file_type_data['extension']
            )
            if not existing:
                file_type = self.env['cloud_storage.file.type'].create({
                    'config_id': self.id,
                    **file_type_data
                })
                created_types.append(file_type)
        
        return created_types
    
    def fix_sync_configuration(self):
        """Fix sync configuration by removing invalid models and creating defaults"""
        self.ensure_one()
        
        # Remove all invalid model configurations
        cleanup_result = self.cleanup_invalid_model_configs()
        
        # Create default model configurations
        model_configs = self.create_default_model_configs()
        
        # Create default file types
        file_types = self.create_default_file_types()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f"Configuration fixed: {cleanup_result['message']}. Created {len(model_configs)} model configs and {len(file_types)} file types.",
                'type': 'success'
            }
        }
    
    def cleanup_invalid_model_configs(self):
        """Remove model configurations that reference non-existent models"""
        self.ensure_one()
        
        # Use SQL to bypass the constrains validation during deletion
        invalid_config_ids = []
        config_names = []
        
        for model_config in self.model_config_ids:
            if model_config.model_name not in self.env:
                invalid_config_ids.append(model_config.id)
                config_names.append(model_config.display_name)
        
        if invalid_config_ids:
            # Delete using SQL to bypass validation
            self.env.cr.execute(
                "DELETE FROM cloud_storage_model_config WHERE id IN %s",
                (tuple(invalid_config_ids),)
            )
            
            return {
                'success': True,
                'message': f'Removed {len(invalid_config_ids)} invalid model configurations: {", ".join(config_names)}'
            }
        else:
            return {
                'success': True,
                'message': 'No invalid model configurations found'
            }
    
    def clear_file_cache(self):
        """Clear the in-memory file cache"""
        self.ensure_one()
        from . import ir_attachment
        ir_attachment._file_cache.clear()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': 'File cache cleared successfully',
                'type': 'success'
            }
        }

    def action_check_and_refresh_tokens(self):
        """Check all active configurations and refresh tokens if needed"""
        try:
            active_configs = self.search([('is_active', '=', True)])
            refreshed_count = 0
            error_count = 0
            status_details = []
            
            for config in active_configs:
                if config.auth_id and config.auth_id.state == 'authorized':
                    try:
                        # This will automatically refresh if needed
                        config.auth_id._get_valid_token()
                        refreshed_count += 1
                        status_details.append(f"✓ {config.name}: Token válido")
                        _logger.info(f"Token checked/refreshed for config: {config.name}")
                    except Exception as e:
                        error_count += 1
                        status_details.append(f"✗ {config.name}: {str(e)}")
                        _logger.error(f"Error checking/refreshing token for config {config.name}: {str(e)}")
                else:
                    status_details.append(f"- {config.name}: Sin autenticación válida")
            
            # Create detailed message
            if status_details:
                message = f"Verificación completada:\n" + "\n".join(status_details)
            else:
                message = "No se encontraron configuraciones activas para verificar"
            
            notification_type = 'success' if error_count == 0 else 'warning'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': message,
                    'type': notification_type,
                    'sticky': True  # Make notification sticky for detailed info
                }
            }
            
        except Exception as e:
            _logger.error(f"Error in token check and refresh: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Error al verificar tokens: {str(e)}",
                    'type': 'danger'
                }
            }

    def action_force_token_refresh(self):
        """Force refresh all tokens regardless of expiry"""
        try:
            active_configs = self.search([('is_active', '=', True)])
            refreshed_count = 0
            error_count = 0
            
            for config in active_configs:
                if config.auth_id and config.auth_id.state == 'authorized':
                    try:
                        # Force refresh by calling refresh_access_token directly
                        if config.auth_id.refresh_access_token():
                            refreshed_count += 1
                            _logger.info(f"Token force refreshed for config: {config.name}")
                        else:
                            error_count += 1
                            _logger.error(f"Failed to force refresh token for config: {config.name}")
                    except Exception as e:
                        error_count += 1
                        _logger.error(f"Error force refreshing token for config {config.name}: {str(e)}")
            
            message = f"Refresco forzado completado: {refreshed_count} tokens actualizados, {error_count} errores"
            notification_type = 'success' if error_count == 0 else 'warning'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': message,
                    'type': notification_type
                }
            }
            
        except Exception as e:
            _logger.error(f"Error in force token refresh: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Error al refrescar tokens: {str(e)}",
                    'type': 'danger'
                }
            }

    @api.model
    def action_global_token_status(self):
        """Global action to check token status from menu"""
        return self.action_check_and_refresh_tokens()


class CloudStorageModelConfig(models.Model):
    _name = 'cloud_storage.model.config'
    _description = 'Model Sync Configuration'
    _rec_name = 'display_name'

    config_id = fields.Many2one('cloud_storage.config', 'Configuration', required=True, ondelete='cascade')
    model_name = fields.Char('Model Name', required=True, help="Technical name of the model (e.g., 'res.partner')")
    display_name = fields.Char('Display Name', required=True, help="Human readable name for the model")
    field_name = fields.Char('Attachment Field', required=True, 
                           help="Field name that contains the file attachment")
    is_active = fields.Boolean('Active', default=True)
    drive_folder_name = fields.Char('Drive Folder Name', 
                                  help="Specific folder in Drive for this model")

    @api.constrains('model_name')
    def _check_model_exists(self):
        for record in self:
            if record.model_name and record.model_name not in self.env:
                raise ValidationError(f"Model '{record.model_name}' does not exist in this Odoo instance")
    
    @api.constrains('model_name', 'config_id')
    def _check_unique_model_config(self):
        for record in self:
            existing = self.search([
                ('model_name', '=', record.model_name),
                ('config_id', '=', record.config_id.id),
                ('id', '!=', record.id)
            ])
            if existing:
                raise ValidationError(f"Model {record.display_name} already configured for this sync configuration")


class CloudStorageFileType(models.Model):
    _name = 'cloud_storage.file.type'
    _description = 'Allowed File Types'
    _rec_name = 'extension'

    config_id = fields.Many2one('cloud_storage.config', 'Configuration', required=True, ondelete='cascade')
    extension = fields.Char('File Extension', required=True, help="e.g., pdf, jpg, png")
    description = fields.Char('Description')
    max_size_mb = fields.Float('Max Size (MB)', default=50.0)
    is_active = fields.Boolean('Active', default=True)

    @api.onchange('extension')
    def _onchange_extension_format(self):
        if self.extension:
            ext = self.extension.lower().strip()
            if ext.startswith('.'):
                ext = ext[1:]
            self.extension = ext

    @api.constrains('extension', 'config_id')
    def _check_unique_extension(self):
        for record in self:
            existing = self.search([
                ('extension', '=', record.extension),
                ('config_id', '=', record.config_id.id),
                ('id', '!=', record.id)
            ])
            if existing:
                raise ValidationError(f"Extension {record.extension} already exists in this configuration")


class CloudStorageSyncLog(models.Model):
    _name = 'cloud_storage.sync.log'
    _description = 'Synchronization Log'
    _order = 'sync_date desc'
    _rec_name = 'display_name'

    display_name = fields.Char('Display Name', compute='_compute_display_name', store=True)
    sync_date = fields.Datetime('Sync Date', default=fields.Datetime.now, required=True)
    sync_type = fields.Selection([
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
        ('complete_batch', 'Complete Batch Sync')
    ], required=True)
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
        ('partial', 'Partial Success'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed')
    ], required=True)
    model_name = fields.Char('Model', required=True)
    record_id = fields.Integer('Record ID')
    file_name = fields.Char('File Name', required=True)
    original_path = fields.Char('Original Path')
    drive_url = fields.Char('Drive URL')
    drive_file_id = fields.Char('Drive File ID')
    error_message = fields.Text('Error Message')
    file_size_bytes = fields.Integer('File Size (Bytes)')
    config_id = fields.Many2one('cloud_storage.config', 'Configuration')
    
    # Batch session tracking fields
    start_time = fields.Datetime('Start Time')
    end_time = fields.Datetime('End Time')
    last_update = fields.Datetime('Last Update')
    total_success = fields.Integer('Total Success', default=0)
    total_errors = fields.Integer('Total Errors', default=0)
    total_processed = fields.Integer('Total Processed', default=0)
    progress_percentage = fields.Float('Progress %', compute='_compute_progress_percentage')

    @api.depends('total_success', 'total_errors', 'total_processed')
    def _compute_progress_percentage(self):
        for record in self:
            if record.total_processed > 0:
                record.progress_percentage = (record.total_processed / max(record.total_processed, 1)) * 100
            else:
                record.progress_percentage = 0.0

    @api.depends('file_name', 'model_name', 'sync_date')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.file_name} ({record.model_name}) - {record.sync_date.strftime('%Y-%m-%d %H:%M') if record.sync_date else ''}"

    def action_retry_sync(self):
        self.ensure_one()
        if self.status == 'success':
            raise UserError("Cannot retry successful synchronization")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': "Retry functionality will be implemented in sync service",
                'type': 'info'
            }
        }
