# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
import logging
import os
import time
from datetime import datetime

_logger = logging.getLogger(__name__)


class CloudStorageOAuth(http.Controller):
    
    @http.route('/cloud_storage/oauth/callback', type='http', auth='user', methods=['GET'])
    def oauth_callback(self, **kwargs):
        """Handle OAuth callback from Google Drive"""
        
        try:
            code = kwargs.get('code')
            state = kwargs.get('state')
            error = kwargs.get('error')
            
            if error:
                return f"""
                <html><body>
                    <h1>OAuth Error</h1>
                    <p>Error: {error}</p>
                    <p>Description: {kwargs.get('error_description', 'Unknown error')}</p>
                </body></html>
                """
            
            if not code:
                return f"""
                <html><body>
                    <h1>OAuth Error</h1>
                    <p>No authorization code received</p>
                </body></html>
                """
            
            if not state or not state.startswith('auth_'):
                return f"""
                <html><body>
                    <h1>OAuth Error</h1>
                    <p>Invalid state parameter</p>
                </body></html>
                """
            
            # Extract auth record ID from state
            try:
                auth_id = int(state.replace('auth_', ''))
            except ValueError:
                return f"""
                <html><body>
                    <h1>OAuth Error</h1>
                    <p>Invalid state format</p>
                </body></html>
                """
            
            # Find the auth record
            auth_record = request.env['cloud_storage.auth'].browse(auth_id)
            if not auth_record.exists():
                return f"""
                <html><body>
                    <h1>OAuth Error</h1>
                    <p>Authentication record not found</p>
                </body></html>
                """
            
            # Exchange code for token
            success = auth_record.exchange_code_for_token(code)
            
            if success:
                return f"""
                <html><body>
                    <h1>OAuth Success!</h1>
                    <p>Successfully authorized Google Drive access for: {auth_record.name}</p>
                    <p>You can close this window and return to Odoo.</p>
                    <script>
                        setTimeout(function() {{ window.close(); }}, 3000);
                    </script>
                </body></html>
                """
            else:
                return f"""
                <html><body>
                    <h1>OAuth Error</h1>
                    <p>Failed to exchange authorization code for access token</p>
                </body></html>
                """
                
        except Exception as e:
            _logger.error(f'OAuth callback error: {str(e)}')
            return f"""
            <html><body>
                <h1>OAuth Error</h1>
                <p>Internal error: {str(e)}</p>
            </body></html>
            """
    
    @http.route('/cloud_storage/oauth/test', type='http', auth='user')
    def oauth_test(self, **kwargs):
        """Test page for OAuth development"""
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        callback_url = f"{base_url}/cloud_storage/oauth/callback"
        
        return f"""
        <html>
        <head><title>OAuth Development Test</title></head>
        <body>
            <h1>OAuth Development Setup</h1>
            <p><strong>Callback URL to configure in Google Console:</strong></p>
            <p><code>{callback_url}</code></p>
            <p>Make sure this URL is added to your Google OAuth application's authorized redirect URIs.</p>
        </body>
        </html>
        """

    @http.route('/cloud_storage/file/<int:attachment_id>', type='http', auth='user', methods=['GET'])
    def serve_cloud_file(self, attachment_id, **kwargs):
        """Serve file from cloud storage with proper access control"""
        _logger.info(f"[CLOUD_STORAGE] HTTP controller called for attachment_id: {attachment_id}")
        
        try:
            attachment = request.env['ir.attachment'].browse(attachment_id)
            _logger.info(f"[CLOUD_STORAGE] Found attachment: {attachment.name if attachment.exists() else 'Not found'}")
            
            # Check if attachment exists and user has access
            if not attachment.exists():
                _logger.warning(f"[CLOUD_STORAGE] Attachment {attachment_id} not found")
                return request.not_found()
            
            # Check if user has access to the attachment
            try:
                attachment.check('read')
                _logger.info(f"[CLOUD_STORAGE] User has read access to attachment {attachment_id}")
            except:
                _logger.warning(f"[CLOUD_STORAGE] User does not have read access to attachment {attachment_id}")
                return request.not_found()
            
            # Check if it's a cloud-synced file
            if attachment.cloud_sync_status != 'synced' or not attachment.cloud_file_id:
                _logger.warning(f"[CLOUD_STORAGE] Attachment {attachment_id} not synced or no cloud file id. Status: {attachment.cloud_sync_status}, has_file_id: {bool(attachment.cloud_file_id)}")
                return request.not_found()
            
            _logger.info(f"[CLOUD_STORAGE] Downloading from cloud for attachment {attachment_id}")
            
            # Helpers de cache
            def _get_cache_root():
                params = request.env['ir.config_parameter'].sudo()
                root = params.get_param('cloud_storage.cache_dir')
                if not root:
                    # Carpeta temporal por defecto
                    root = '/var/tmp/odoo_cloud_cache'
                try:
                    os.makedirs(root, exist_ok=True)
                except Exception as mkdir_err:
                    _logger.warning(f"[CLOUD_STORAGE] No se pudo crear cache_dir {root}: {mkdir_err}")
                return root

            def _cache_path(file_id: str) -> str:
                return os.path.join(_get_cache_root(), file_id)

            def _is_expired(path: str) -> bool:
                ttl = int(request.env['ir.config_parameter'].sudo().get_param('cloud_storage.cache_ttl_seconds', 86400))
                try:
                    mtime = os.path.getmtime(path)
                    return (time.time() - mtime) > ttl
                except Exception:
                    return True

            def _enforce_cache_quota():
                params = request.env['ir.config_parameter'].sudo()
                max_mb = int(params.get_param('cloud_storage.cache_max_size_mb', 1024))
                max_bytes = max_mb * 1024 * 1024
                root = _get_cache_root()
                try:
                    entries = []
                    total = 0
                    for name in os.listdir(root):
                        path = os.path.join(root, name)
                        if os.path.isfile(path):
                            try:
                                size = os.path.getsize(path)
                                mtime = os.path.getmtime(path)
                                total += size
                                entries.append((mtime, size, path))
                            except Exception:
                                continue
                    if total <= max_bytes:
                        return
                    # Ordenar por mtime asc (más antiguo primero)
                    entries.sort(key=lambda x: x[0])
                    target = int(max_bytes * 0.9)
                    for _, size, path in entries:
                        try:
                            os.remove(path)
                            total -= size
                            if total <= target:
                                break
                        except Exception as rm_err:
                            _logger.warning(f"[CLOUD_STORAGE] Fallo purgando cache {path}: {rm_err}")
                except Exception as e:
                    _logger.warning(f"[CLOUD_STORAGE] No se pudo aplicar cuota de cache: {e}")

            # Descargar usando la API autenticada de Drive, con cache en disco
            file_id = attachment.cloud_file_id
            if not file_id and attachment.cloud_storage_url and 'drive.google.com/file/d/' in attachment.cloud_storage_url:
                try:
                    file_id = attachment.cloud_storage_url.split('/d/')[1].split('/')[0]
                except Exception:
                    file_id = None
            if not file_id:
                _logger.error(f"[CLOUD_STORAGE] No cloud_file_id for attachment {attachment_id}")
                return request.not_found()

            cache_file = _cache_path(file_id)

            start_time = time.time()
            bytes_served = 0
            cache_hit = False
            http_status = 200
            range_header_value = request.httprequest.headers.get('Range')

            # Si cache existente y no expirado, servir desde cache con soporte Range
            if os.path.exists(cache_file) and not _is_expired(cache_file):
                try:
                    file_size = os.path.getsize(cache_file)
                    if range_header_value and range_header_value.startswith('bytes='):
                        try:
                            range_spec = range_header_value.replace('bytes=', '')
                            start_str, end_str = range_spec.split('-')
                            start = int(start_str) if start_str else 0
                            end = int(end_str) if end_str else file_size - 1
                            if start < 0 or end >= file_size or start > end:
                                raise ValueError('Invalid range')
                            length = end - start + 1
                            with open(cache_file, 'rb') as fh:
                                fh.seek(start)
                                data = fh.read(length)
                            bytes_served = len(data)
                            cache_hit = True
                            headers = [
                                ('Content-Type', attachment.mimetype or 'application/octet-stream'),
                                ('Content-Length', str(len(data))),
                                ('Accept-Ranges', 'bytes'),
                                ('Content-Range', f'bytes {start}-{end}/{file_size}'),
                                ('Content-Disposition', f'inline; filename="{attachment.name}"'),
                            ]
                            http_status = 206
                            resp = request.make_response(data, headers=headers, status=206)
                            duration_ms = int((time.time() - start_time) * 1000)
                            try:
                                request.env['cloud_storage.access.log'].sudo().create({
                                    'user_id': request.env.user.id,
                                    'attachment_id': attachment.id,
                                    'bytes_served': bytes_served,
                                    'cache_hit': cache_hit,
                                    'http_status': http_status,
                                    'duration_ms': duration_ms,
                                    'range_request': range_header_value,
                                    'user_agent': request.httprequest.headers.get('User-Agent'),
                                    'ip_address': request.httprequest.remote_addr,
                                })
                            except Exception:
                                pass
                            return resp
                        except Exception as parse_err:
                            _logger.warning(f"[CLOUD_STORAGE] Range inválido: {parse_err}")
                    # Sin Range o inválido: servir completo
                    with open(cache_file, 'rb') as fh:
                        data = fh.read()
                    bytes_served = len(data)
                    cache_hit = True
                    headers = [
                        ('Content-Type', attachment.mimetype or 'application/octet-stream'),
                        ('Content-Length', str(len(data))),
                        ('Content-Disposition', f'inline; filename="{attachment.name}"'),
                    ]
                    # Touch para LRU por mtime
                    try:
                        os.utime(cache_file, None)
                    except Exception:
                        pass
                    resp = request.make_response(data, headers=headers)
                    duration_ms = int((time.time() - start_time) * 1000)
                    try:
                        request.env['cloud_storage.access.log'].sudo().create({
                            'user_id': request.env.user.id,
                            'attachment_id': attachment.id,
                            'bytes_served': bytes_served,
                            'cache_hit': cache_hit,
                            'http_status': http_status,
                            'duration_ms': duration_ms,
                            'range_request': range_header_value,
                            'user_agent': request.httprequest.headers.get('User-Agent'),
                            'ip_address': request.httprequest.remote_addr,
                        })
                    except Exception:
                        pass
                    return resp
                except Exception as e:
                    _logger.warning(f"[CLOUD_STORAGE] Fallo leyendo cache, se intentará redescargar: {e}")

            # No hay cache válido: intentar Range directo desde Drive; si no, descargar y cachear
            try:
                Config = request.env['cloud_storage.config'].sudo()
                config = Config.get_active_config()
                if not config or not config.auth_id or config.auth_id.state != 'authorized':
                    _logger.error("[CLOUD_STORAGE] No hay configuración activa/autorizada para descargar")
                    return request.not_found()

                sync_service = request.env['cloud_storage.sync.service']
                service = sync_service._get_google_drive_service(config.auth_id)

                # Passthrough de Range si el cliente lo solicita
                if range_header_value and range_header_value.startswith('bytes='):
                    try:
                        status_code, resp_headers, content = sync_service._http_get_drive_range(
                            config.auth_id.access_token, file_id, range_header_value
                        )
                        bytes_served = len(content)
                        http_status = status_code
                        headers = [
                            ('Content-Type', attachment.mimetype or 'application/octet-stream'),
                            ('Content-Length', str(len(content))),
                            ('Accept-Ranges', 'bytes'),
                        ]
                        cr = resp_headers.get('Content-Range') or resp_headers.get('content-range')
                        if cr:
                            headers.append(('Content-Range', cr))
                        headers.append(('Content-Disposition', f'inline; filename="{attachment.name}"'))
                        resp = request.make_response(content, headers=headers, status=status_code)
                        duration_ms = int((time.time() - start_time) * 1000)
                        try:
                            request.env['cloud_storage.access.log'].sudo().create({
                                'user_id': request.env.user.id,
                                'attachment_id': attachment.id,
                                'bytes_served': bytes_served,
                                'cache_hit': cache_hit,
                                'http_status': http_status,
                                'duration_ms': duration_ms,
                                'range_request': range_header_value,
                                'user_agent': request.httprequest.headers.get('User-Agent'),
                                'ip_address': request.httprequest.remote_addr,
                            })
                        except Exception:
                            pass
                        return resp
                    except Exception as passthrough_err:
                        _logger.warning(f"[CLOUD_STORAGE] Falló Range passthrough, se descargará completo: {passthrough_err}")

                # Descargar completo con backoff, cachear y servir
                content = sync_service._download_drive_file_with_backoff(service, file_id)

                # Escribir cache en disco
                try:
                    with open(cache_file, 'wb') as out:
                        out.write(content)
                    _enforce_cache_quota()
                except Exception as werr:
                    _logger.warning(f"[CLOUD_STORAGE] No se pudo escribir cache {cache_file}: {werr}")

                bytes_served = len(content)
                headers = [
                    ('Content-Type', attachment.mimetype or 'application/octet-stream'),
                    ('Content-Length', str(len(content))),
                    ('Content-Disposition', f'inline; filename="{attachment.name}"'),
                ]
                resp = request.make_response(content, headers=headers)
                duration_ms = int((time.time() - start_time) * 1000)
                try:
                    request.env['cloud_storage.access.log'].sudo().create({
                        'user_id': request.env.user.id,
                        'attachment_id': attachment.id,
                        'bytes_served': bytes_served,
                        'cache_hit': cache_hit,
                        'http_status': http_status,
                        'duration_ms': duration_ms,
                        'range_request': range_header_value,
                        'user_agent': request.httprequest.headers.get('User-Agent'),
                        'ip_address': request.httprequest.remote_addr,
                    })
                except Exception:
                    pass
                return resp
            except Exception as e:
                _logger.error(f"[CLOUD_STORAGE] Error descargando por API: {str(e)}")
                # Responder con 503 para permitir reintentos del cliente
                http_status = 503
                duration_ms = int((time.time() - start_time) * 1000)
                try:
                    request.env['cloud_storage.access.log'].sudo().create({
                        'user_id': request.env.user.id,
                        'attachment_id': attachment.id,
                        'bytes_served': bytes_served,
                        'cache_hit': cache_hit,
                        'http_status': http_status,
                        'duration_ms': duration_ms,
                        'range_request': range_header_value,
                        'user_agent': request.httprequest.headers.get('User-Agent'),
                        'ip_address': request.httprequest.remote_addr,
                    })
                except Exception:
                    pass
                return request.make_response('Service Unavailable', headers=[('Content-Type', 'text/plain')], status=503)
                
        except Exception as e:
            _logger.error(f'[CLOUD_STORAGE] Exception in HTTP controller for {attachment_id}: {str(e)}')
            return request.not_found()
