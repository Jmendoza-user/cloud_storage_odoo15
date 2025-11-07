# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Module Overview

**cloud_storage** - Odoo 15 module for syncing attachments to Google Drive via OAuth2. Reduces local storage by moving files to cloud while maintaining Odoo access through a proxy controller.

**Key Problem Solved**: Large attachments consume database/filestore space. This module uploads files to Google Drive and optionally deletes local copies, while providing transparent access via `/cloud_storage/file/<id>` proxy URLs.

## Development Commands

### Install/Update Module

```bash
# Install module in Odoo 15
python3 /odoo15/odoo-server/odoo-bin \
  -c /etc/odoo15-1-server.conf \
  -d environmentodoo \
  -i cloud_storage \
  --stop-after-init

# Update module after changes
python3 /odoo15/odoo-server/odoo-bin \
  -c /etc/odoo15-1-server.conf \
  -d environmentodoo \
  -u cloud_storage \
  --stop-after-init

# Run in development mode with auto-reload
python3 /odoo15/odoo-server/odoo-bin \
  -c /etc/odoo15-1-server.conf \
  -d environmentodoo \
  -u cloud_storage \
  --dev=all
```

### Test OAuth Flow

```bash
# Access OAuth callback URL directly (replace with your server)
# http://10.10.6.222:8089/cloud_storage/oauth/callback

# Test file proxy endpoint
# http://10.10.6.222:8089/cloud_storage/file/<attachment_id>
```

### Manual Sync from Shell

```python
# Open Odoo shell
python3 /odoo15/odoo-server/odoo-bin shell -d environmentodoo

# In Python shell:
config = env['cloud_storage.config'].search([('is_active', '=', True)], limit=1)
sync_service = env['cloud_storage.sync.service']
sync_service.manual_sync(config.id, limit=10)

# Test single attachment sync
attachment = env['ir.attachment'].browse(123)
attachment.sync_to_cloud()

# Check sync logs
logs = env['cloud_storage.sync.log'].search([], limit=20, order='sync_date desc')
for log in logs:
    print(f"{log.sync_date} | {log.attachment_id.name} | {log.status}")
```

### Trigger Cron Jobs Manually

```bash
# Run automatic sync cron
python3 /odoo15/odoo-server/odoo-bin shell -d environmentodoo -c "env['cloud_storage.sync.service'].automatic_sync()"

# Run token refresh cron
python3 /odoo15/odoo-server/odoo-bin shell -d environmentodoo -c "env['cloud_storage.config'].action_check_and_refresh_tokens()"

# Run reconciliation cron
python3 /odoo15/odoo-server/odoo-bin shell -d environmentodoo -c "env['cloud_storage.sync.service'].reconcile_cloud_references(200)"
```

## Module Architecture

### Core Models

1. **`cloud_storage.auth`** (`models/models.py`)
   - OAuth2 credentials and tokens
   - Methods: `get_auth_url()`, `exchange_code_for_token()`, `refresh_access_token()`, `_get_valid_token()`
   - Key fields: `access_token`, `refresh_token`, `token_expiry`, `state`

2. **`cloud_storage.config`** (`models/models.py`)
   - Main configuration singleton
   - Links to auth, model configs, and file types
   - Methods: `action_manual_sync()`, `get_active_config()`, `action_check_and_refresh_tokens()`

3. **`cloud_storage.model.config`** (`models/models.py`)
   - Per-model sync configuration (which Odoo models to sync)
   - Fields: `model_name`, `attachment_field`, `drive_folder_name`, `is_active`
   - Example: Configure `product.product` to sync to "Products" folder

4. **`cloud_storage.file.type`** (`models/models.py`)
   - Whitelist of allowed file extensions
   - Fields: `extension` (e.g., "pdf", "jpg"), `is_active`

5. **`cloud_storage.sync.log`** (`models/models.py`)
   - Audit trail of all sync operations
   - Fields: `attachment_id`, `status`, `sync_date`, `error_message`, `file_size_mb`

6. **`cloud_storage.sync.service`** (`models/sync_service.py`)
   - Core sync engine with Google Drive API integration
   - Methods: `manual_sync()`, `automatic_sync()`, `_sync_file()`, `_get_google_drive_service()`
   - Implements exponential backoff for rate limits (429) and server errors (5xx)

7. **`ir.attachment`** (extended in `models/ir_attachment.py`)
   - Added fields: `cloud_file_id`, `cloud_storage_url`, `cloud_sync_status`, `cloud_synced_date`
   - Methods: `sync_to_cloud()`, `restore_from_cloud()`
   - Overrides: `_get_datas()`, `_compute_raw()`, `_file_read()` for transparent cloud access

8. **`cloud_storage.access.log`** (`models/access_log.py`)
   - Performance monitoring for proxy downloads
   - Tracks cache hits, bytes served, duration, HTTP status

### Controllers

**`controllers/controllers.py`**:
- `/cloud_storage/oauth/callback` - OAuth2 callback handler (exchanges code for token)
- `/cloud_storage/file/<int:attachment_id>` - Proxy for downloading files from Drive
  - Supports HTTP range requests for streaming large files
  - Validates access permissions via `ir.attachment` rules
  - Logs access in `cloud_storage.access.log`

### OAuth2 Flow

1. User clicks "Authorize" button in `cloud_storage.auth` form
2. `action_authorize()` → generates Google auth URL with state parameter
3. User authenticates in Google → redirected to `/cloud_storage/oauth/callback?code=...&state=auth_<id>`
4. Controller extracts code → calls `exchange_code_for_token(code)`
5. Token stored in `access_token`, `refresh_token` fields
6. `state` changes to 'authorized'

### Sync Process Architecture

**Manual Sync** (`action_manual_sync`):
1. Validate active config and auth
2. For each active `model_config`:
   - Query `ir.attachment` WHERE `res_model = model_config.model_name`
   - Filter by `cloud_sync_status IN ('local', 'error')`
   - Filter by allowed file extensions from `file_type_ids`
   - Limit results (default 500, configurable via `limit` parameter)
3. For each attachment:
   - Upload to Drive via `MediaIoBaseUpload` (resumable)
   - Create/find folder by `drive_folder_name`
   - Store `cloud_file_id` and update status to 'synced'
   - Optionally delete local `datas` if `delete_local_after_sync=True`
   - Log result in `cloud_storage.sync.log`
4. Return summary (files synced, errors, space freed)

**Automatic Sync** (cron: daily):
- Same as manual sync but processes all active configs
- No limit (processes all pending files)
- Includes exponential backoff for rate limits

### Token Management

**Token Refresh Strategy**:
- Tokens expire after ~1 hour (Google default)
- `_get_valid_token()` checks expiry and auto-refreshes if < 5 minutes remaining
- Cron job runs every 6 hours to proactively refresh tokens
- `refresh_access_token()` uses `refresh_token` to get new `access_token`

**Token Status States**:
- `draft` - Initial state, no tokens
- `pending` - Authorization URL generated
- `authorized` - Valid tokens obtained
- `expired` - Token expired, needs refresh
- `error` - Refresh failed, needs re-authorization

## Key Technical Details

### Transparent File Access

When `delete_local_after_sync=True`, `datas` field is cleared but file remains accessible:

1. Odoo's `ir.attachment._file_read()` is overridden
2. If `cloud_file_id` exists and `datas` is empty → download from Drive
3. In-memory cache (`_file_cache`) stores last 50 files for 5 minutes
4. Web access via `/cloud_storage/file/<id>` validates permissions first

### Performance Optimizations

**Implemented** (as of latest commit):
- Exponential backoff with jitter for 429/5xx errors (`_execute_with_backoff`)
- Fast-path checks in `_get_datas()` and `_compute_raw()` (skip if no synced files)
- Reduced logging for common operations
- HTTP range request support in proxy for streaming video/PDF
- In-memory LRU cache for recently downloaded files
- Batch processing with configurable limits

**Not Yet Implemented** (see `mejoras.md`):
- Persistent disk cache for thumbnails
- Pre-generation of image variants (`image_128`, `image_256`)
- Queue-based sync with job isolation
- Circuit breaker for prolonged Drive outages

### Security Considerations

**Current Implementation**:
- Public permissions (`anyone` with link) were removed (see `mejoras.md` line 10)
- Proxy validates Odoo access rights before serving files
- Only whitelisted models and extensions can be synced
- OAuth tokens stored in database (consider encrypting in production)

**Recommendations** (from `mejoras.md`):
- Use service account instead of OAuth for server-to-server access
- Implement role-based folder permissions in Drive
- Audit logs track all downloads via `cloud_storage.access.log`
- Never sync `ir.attachment` records with sensitive system files

### Reconciliation Process

**`reconcile_cloud_references(limit=200)`**:
- Finds attachments with `cloud_file_id` but `type != 'url'` (inconsistent state)
- Converts `type` to 'url' and sets `url` to proxy endpoint
- Useful after bulk imports or database migrations
- Runs daily via cron

## Common Development Tasks

### Add New Model for Sync

1. Go to **Cloud Storage > Configuration > Model Configurations**
2. Create new record:
   - **Model Name**: Technical name (e.g., `sale.order`)
   - **Display Name**: Human-readable name
   - **Drive Folder Name**: Google Drive folder name
   - **Active**: True
3. Ensure file extensions are configured in **File Types**
4. Run manual sync to test

### Debug Sync Failures

```python
# Check recent errors
logs = env['cloud_storage.sync.log'].search([('status', '=', 'error')], limit=10)
for log in logs:
    print(f"{log.attachment_id.name}: {log.error_message}")

# Check attachment sync status
attachment = env['ir.attachment'].browse(123)
print(f"Status: {attachment.cloud_sync_status}")
print(f"Cloud ID: {attachment.cloud_file_id}")
print(f"Last synced: {attachment.cloud_synced_date}")

# Retry failed sync
attachment.cloud_sync_status = 'local'
attachment.sync_to_cloud()
```

### Test Proxy Download

```bash
# Get attachment ID
attachment_id=123

# Test proxy with curl (authenticated)
curl -v -H "Cookie: session_id=YOUR_SESSION" \
  http://10.10.6.222:8089/cloud_storage/file/${attachment_id}

# Test range request (for video/PDF streaming)
curl -H "Range: bytes=0-1023" \
  -H "Cookie: session_id=YOUR_SESSION" \
  http://10.10.6.222:8089/cloud_storage/file/${attachment_id}
```

### Monitor Token Status

```python
# Check all auth configs
auths = env['cloud_storage.auth'].search([])
for auth in auths:
    print(f"{auth.name}: {auth.state}")
    if auth.token_expiry:
        from datetime import datetime
        delta = auth.token_expiry - datetime.now()
        print(f"  Expires in: {delta.total_seconds() / 60:.1f} minutes")

# Force refresh all tokens
env['cloud_storage.config'].action_force_refresh_tokens()
```

### Query Sync Statistics

```python
# Total synced files
synced_count = env['ir.attachment'].search_count([('cloud_sync_status', '=', 'synced')])
print(f"Total synced: {synced_count}")

# Space saved (approximate)
synced_files = env['ir.attachment'].search([('cloud_sync_status', '=', 'synced')])
total_mb = sum(att.cloud_size_bytes or 0 for att in synced_files) / (1024 * 1024)
print(f"Total size synced: {total_mb:.2f} MB")

# Files by model
env.cr.execute("""
    SELECT res_model, COUNT(*), SUM(cloud_size_bytes)/1024/1024 as mb
    FROM ir_attachment
    WHERE cloud_sync_status = 'synced'
    GROUP BY res_model
    ORDER BY mb DESC
""")
print(env.cr.fetchall())
```

## Cron Jobs

Three cron jobs are configured in `data/cron_data.xml`:

1. **Cloud Storage: Automatic Sync** (daily)
   - Syncs all pending attachments matching active configurations
   - Model: `cloud_storage.sync.service`
   - Method: `automatic_sync()`

2. **Cloud Storage: Token Refresh** (every 6 hours)
   - Proactively refreshes tokens before expiry
   - Model: `cloud_storage.config`
   - Method: `action_check_and_refresh_tokens()`

3. **Cloud Storage: Reconcile References** (daily)
   - Fixes inconsistent attachment states
   - Model: `cloud_storage.sync.service`
   - Method: `reconcile_cloud_references(200)`

Modify intervals via **Settings > Technical > Automation > Scheduled Actions**

## Dependencies

### Python Packages (Required)

```bash
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2 requests
```

### Odoo Modules

- `base` - Core Odoo framework
- `web` - Web client
- Standard `ir.attachment` model

## Troubleshooting

### "No access token available"
- Check `cloud_storage.auth` record has `state='authorized'`
- Verify `access_token` and `refresh_token` are not empty
- Try manual token refresh: `auth.refresh_access_token()`

### "Token expired" errors
- Run: `env['cloud_storage.config'].action_check_and_refresh_tokens()`
- If fails, re-authorize: Click "Authorize" button in auth form

### Files not syncing
- Verify model is in active `cloud_storage.model.config`
- Check file extension is in active `cloud_storage.file.type`
- Ensure `cloud_sync_status = 'local'` (not already synced)
- Check logs: `env['cloud_storage.sync.log'].search([], limit=10, order='id desc')`

### Proxy download fails (404/500)
- Verify attachment has `cloud_file_id` set
- Test Drive connectivity: `auth.action_test_connection()`
- Check access rights: User must have permission to view attachment
- Enable debug logging: Set `--log-level=debug` in config

### Rate limit errors (429)
- Module has exponential backoff, but aggressive syncing may hit limits
- Reduce batch size: Pass `limit=50` to `manual_sync()`
- Increase cron interval from daily to weekly
- Consider Google Workspace account for higher quotas

## Configuration Files Referenced

- `/etc/odoo15-1-server.conf` - Main Odoo 15 config (db: environmentodoo, port 8089)
- Default redirect URI: `http://10.10.6.222:8089/cloud_storage/oauth/callback`

## Additional Documentation

- `README.md` - User-facing documentation with setup guide
- `REQUIREMENTS.md` - Functional requirements and current status
- `ADD_MODEL_CONFIGS.md` - How to configure model-specific syncing
- `TOKEN_REFRESH_GUIDE.md` - Detailed token refresh workflow
- `mejoras.md` - Performance analysis and future improvements (in Spanish)
