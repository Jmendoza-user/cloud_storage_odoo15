# -*- coding: utf-8 -*-

from odoo import models, fields, api
import logging
import time
from functools import lru_cache

_logger = logging.getLogger(__name__)

# Cache global para archivos descargados recientemente (en memoria)
_file_cache = {}
_cache_max_age = 300  # 5 minutos en segundos
_cache_max_size = 50  # Máximo 50 archivos en cache

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    # Cloud storage specific fields
    cloud_storage_url = fields.Char('Cloud Storage URL', help="URL to view file in cloud storage")
    cloud_file_id = fields.Char('Cloud File ID', help="Unique identifier in cloud storage")
    cloud_sync_status = fields.Selection([
        ('pending', 'Pending Sync'),
        ('synced', 'Synced'),
        ('error', 'Sync Error'),
        ('local', 'Local Only')
    ], default='local', string='Cloud Sync Status')
    cloud_synced_date = fields.Datetime('Last Synced', help="When the file was last synced to cloud")
    original_local_path = fields.Char('Original Local Path', help="Original local file path before sync")
    cloud_md5 = fields.Char('Cloud MD5', help="MD5 checksum of the file stored in cloud")
    cloud_size_bytes = fields.Integer('Cloud Size (Bytes)', help="Size in bytes of the file stored in cloud")
    cloud_auth_id = fields.Many2one('cloud_storage.auth', 'Cloud Auth', help="Authentication used to access this file in cloud")
    
    # Campos de cache para optimización
    cloud_cache_key = fields.Char('Cache Key', help="Key for caching downloaded content")
    cloud_last_accessed = fields.Datetime('Last Cloud Access', help="When file was last accessed from cloud")

    @api.model
    def create(self, vals):
        """Set default cloud sync status for new attachments"""
        if 'cloud_sync_status' not in vals:
            vals['cloud_sync_status'] = 'local'
        return super().create(vals)

    def sync_to_cloud(self):
        """Sync this attachment to cloud storage"""
        self.ensure_one()
        if not self.datas:
            return False
        
        # Get active cloud storage configuration
        config = self.env['cloud_storage.config'].get_active_config()
        if not config:
            return False
        
        # Use sync service to upload this specific file
        sync_service = self.env['cloud_storage.sync.service']
        try:
            # Create a mock file_info structure for this attachment
            file_info = {
                'record': self,
                'attachment': self,
                'model_config': None,  # Will be handled in sync service
                'file_extension': self.name.split('.')[-1].lower() if '.' in self.name else ''
            }
            
            service = sync_service._get_google_drive_service(config.auth_id)
            result = sync_service._sync_file(file_info, service, config)
            
            if result['status'] == 'success':
                self.cloud_sync_status = 'synced'
                self.cloud_synced_date = fields.Datetime.now()
                return True
            else:
                self.cloud_sync_status = 'error'
                return False
                
        except Exception as e:
            self.cloud_sync_status = 'error'
            return False

    def restore_from_cloud(self):
        """Restore file data from cloud storage (download back to local)"""
        self.ensure_one()
        if not self.cloud_file_id or not self.cloud_storage_url:
            return False
        
        try:
            import requests
            response = requests.get(self.url)
            if response.status_code == 200:
                import base64
                self.write({
                    'type': 'binary',
                    'datas': base64.b64encode(response.content),
                    'url': False
                })
                return True
        except Exception:
            pass
        return False
    
    def _get_cache_key(self):
        """Generate cache key for this attachment"""
        return f"cloud_file_{self.id}_{self.cloud_file_id}_{self.write_date}"
    
    def _get_from_cache(self, cache_key):
        """Get file content from memory cache"""
        if cache_key not in _file_cache:
            return None
            
        cache_entry = _file_cache[cache_key]
        current_time = time.time()
        
        # Get cache timeout from configuration
        config = self.env['cloud_storage.config'].get_active_config()
        cache_timeout = (config.cache_timeout_minutes * 60) if config else _cache_max_age
        
        # Check if cache entry is still valid
        if current_time - cache_entry['timestamp'] > cache_timeout:
            del _file_cache[cache_key]
            return None
            
        _logger.debug(f"[CLOUD_CACHE] Cache hit for {cache_key}")
        return cache_entry['content']
    
    def _store_in_cache(self, cache_key, content):
        """Store file content in memory cache"""
        # Get max cache size from configuration
        config = self.env['cloud_storage.config'].get_active_config()
        max_cache_size = config.max_cache_size if config else _cache_max_size
        
        # Clean old entries if cache is full
        if len(_file_cache) >= max_cache_size:
            # Remove oldest entries
            oldest_keys = sorted(_file_cache.keys(), 
                               key=lambda k: _file_cache[k]['timestamp'])[:10]
            for old_key in oldest_keys:
                del _file_cache[old_key]
        
        _file_cache[cache_key] = {
            'content': content,
            'timestamp': time.time()
        }
        _logger.debug(f"[CLOUD_CACHE] Stored in cache: {cache_key}")
    
    def _download_from_cloud(self, use_cache=True):
        """Download file from cloud with caching support"""
        _logger.info(f"[CLOUD_DOWNLOAD] Starting download for {self.name}")

        if not self.cloud_file_id:
            _logger.info(f"[CLOUD_DOWNLOAD] No cloud_file_id for {self.name}")
            return None
        
        # Check if cloud access is enabled in configuration
        config = self.env['cloud_storage.config'].get_active_config()
        _logger.info(f"[CLOUD_DOWNLOAD] Config found: {bool(config)}, enable_cloud_access: {config.enable_cloud_access if config else 'N/A'}")
        
        if not config or not config.enable_cloud_access:
            _logger.warning(f"[CLOUD_DOWNLOAD] Cloud access disabled for {self.name}")
            return None
            
        cache_key = self._get_cache_key()
        
        # Try cache first if enabled
        if use_cache:
            cached_content = self._get_from_cache(cache_key)
            if cached_content is not None:
                # Update last accessed time (async to avoid blocking)
                self.env.cr.execute(
                    "UPDATE ir_attachment SET cloud_last_accessed = %s WHERE id = %s",
                    (fields.Datetime.now(), self.id)
                )
                return cached_content
        
        try:
            import base64
            # Usar la API autenticada de Drive
            # Preferir la autenticación asociada al adjunto; fallback a configuración activa
            auth = self.cloud_auth_id
            if not auth or auth.state != 'authorized':
                config = self.env['cloud_storage.config'].sudo().get_active_config()
                auth = config.auth_id if config else False
            if not auth or auth.state != 'authorized':
                _logger.warning(f"[CLOUD_DOWNLOAD] No auth available to download {self.name}")
                return None
            service = self.env['cloud_storage.sync.service']._get_google_drive_service(auth)
            from googleapiclient.http import MediaIoBaseDownload
            import io
            request_drive = service.files().get_media(fileId=self.cloud_file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request_drive)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            content_bytes = fh.getvalue()
            content = base64.b64encode(content_bytes)
            # Store in cache
            if use_cache:
                self._store_in_cache(cache_key, content)
            # Update access time (async)
            self.env.cr.execute(
                "UPDATE ir_attachment SET cloud_last_accessed = %s WHERE id = %s",
                (fields.Datetime.now(), self.id)
            )
            return content
        except Exception as e:
            _logger.error(f"[CLOUD_DOWNLOAD] Error downloading {self.name} via Drive API: {str(e)}")
            return None
    
    def _get_datas(self):
        """Optimized _get_datas with caching support"""
        # Temporary verbose logging to debug the issue - TESTING
        _logger.error(f"[CLOUD_STORAGE_TEST] _get_datas called for attachment ID: {self.id}, name: {getattr(self, 'name', 'NO_NAME')}")
        _logger.error(f"[CLOUD_STORAGE_TEST] Status - cloud_sync_status: {getattr(self, 'cloud_sync_status', 'NO_STATUS')}, type: {getattr(self, 'type', 'NO_TYPE')}")
        _logger.error(f"[CLOUD_STORAGE_TEST] has cloud_storage_url: {bool(getattr(self, 'cloud_storage_url', False))}")
        
        # If this attachment is synced to cloud and we have a cloud file id
        if self.cloud_sync_status == 'synced' and self.cloud_file_id:
            _logger.error(f"[CLOUD_STORAGE_TEST] Attempting cloud download for {getattr(self, 'name', 'NO_NAME')}")
            content = self._download_from_cloud(use_cache=True)
            if content is not None:
                _logger.error(f"[CLOUD_STORAGE_TEST] Successfully got content from cloud for {getattr(self, 'name', 'NO_NAME')}")
                return content
            
            # Fallback to original method if cloud download fails
            _logger.error(f"[CLOUD_STORAGE_TEST] Cloud download failed for {getattr(self, 'name', 'NO_NAME')}, using fallback")
            return super()._get_datas()
        
        _logger.error(f"[CLOUD_STORAGE_TEST] Using original _get_datas for {getattr(self, 'name', 'NO_NAME')}")
        # Use original method for non-synced attachments
        return super()._get_datas()
    
    def _compute_raw(self):
        """Optimized _compute_raw with caching support"""
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(f"[CLOUD_STORAGE] _compute_raw called for {len(self)} attachment(s)")
        
        for attach in self:
            if attach.cloud_sync_status == 'synced' and attach.cloud_file_id:
                # Get content from cache first, then decode from base64 to raw bytes
                content_b64 = attach._download_from_cloud(use_cache=True)
                if content_b64 is not None:
                    import base64
                    attach.raw = base64.b64decode(content_b64)
                else:
                    _logger.warning(f"[CLOUD_STORAGE] Failed to get raw data for {attach.name}")
                    attach.raw = b''
            else:
                # Call original compute method for non-cloud attachments
                super(IrAttachment, attach)._compute_raw()
    
    @api.model
    def _file_read(self, fname):
        """Optimized _file_read with caching support"""
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(f"[CLOUD_STORAGE] _file_read called for fname: {fname}")
        
        # Try to find attachment by store_fname
        attachment = self.search([('store_fname', '=', fname)], limit=1)
        
        if attachment and attachment.cloud_sync_status == 'synced' and attachment.cloud_file_id:
            # Get content from cache and decode to raw bytes
            content_b64 = attachment._download_from_cloud(use_cache=True)
            if content_b64 is not None:
                import base64
                return base64.b64decode(content_b64)
        
        # Fallback to original method
        return super()._file_read(fname)