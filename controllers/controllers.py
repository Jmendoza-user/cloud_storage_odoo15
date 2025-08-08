# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
import logging

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
            if attachment.cloud_sync_status != 'synced' or not attachment.cloud_storage_url:
                _logger.warning(f"[CLOUD_STORAGE] Attachment {attachment_id} not synced or no cloud URL. Status: {attachment.cloud_sync_status}, has_cloud_url: {bool(attachment.cloud_storage_url)}")
                return request.not_found()
            
            _logger.info(f"[CLOUD_STORAGE] Downloading from cloud for attachment {attachment_id}")
            
            # Convert cloud_storage_url to direct download link
            if 'drive.google.com/file/d/' in attachment.cloud_storage_url:
                # Extract file ID from Google Drive URL
                file_id = attachment.cloud_file_id or attachment.cloud_storage_url.split('/d/')[1].split('/')[0]
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            else:
                download_url = attachment.cloud_storage_url
            
            _logger.info(f"[CLOUD_STORAGE] Making request to: {download_url}")
            
            # Download from Google Drive and serve
            import requests
            response = requests.get(download_url, timeout=30)
            
            _logger.info(f"[CLOUD_STORAGE] Download response status: {response.status_code}")
            
            if response.status_code == 200:
                _logger.info(f"[CLOUD_STORAGE] Successfully serving {len(response.content)} bytes")
                
                # Set appropriate headers
                headers = [
                    ('Content-Type', attachment.mimetype or 'application/octet-stream'),
                    ('Content-Length', str(len(response.content))),
                    ('Content-Disposition', f'inline; filename="{attachment.name}"'),
                ]
                
                return request.make_response(
                    response.content,
                    headers=headers
                )
            else:
                _logger.error(f"[CLOUD_STORAGE] Failed to download from cloud, status: {response.status_code}")
                return request.not_found()
                
        except Exception as e:
            _logger.error(f'[CLOUD_STORAGE] Exception in HTTP controller for {attachment_id}: {str(e)}')
            return request.not_found()
