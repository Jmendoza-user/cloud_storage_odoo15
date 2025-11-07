# Guía de Prueba de Sincronización Automática (Cron)

## Problema Original
El cron de sincronización automática se ejecuta en la madrugada y no se pueden ver los logs, dificultando la depuración.

## Solución Implementada

### 1. Prueba Manual del Auto Sync

Hemos agregado un botón **"🔍 Test Auto Sync (Manual)"** en la vista de configuración que:
- Solo aparece cuando `auto_sync = True`
- Ejecuta el mismo código que el cron
- Muestra notificaciones inmediatas con los resultados
- Usa un batch más pequeño (50 archivos) para pruebas rápidas

#### Cómo usar:

1. Ve a **Cloud Storage > Configuration > Sync Configuration**
2. Abre tu configuración
3. Asegúrate de que **Auto Sync** esté activado (checkbox marcado)
4. Haz clic en el botón verde **"🔍 Test Auto Sync (Manual)"**
5. Verás una notificación con los resultados y logs recientes

### 2. Verificar el Estado del Cron

#### Desde la Interfaz Web:

1. Ve a **Settings > Technical > Automation > Scheduled Actions**
2. Busca: **"Cloud Storage: Automatic Sync"**
3. Verifica:
   - **Active**: Debe estar marcado
   - **Interval**: 1 día
   - **Next Execution Date**: Cuándo se ejecutará próximamente
   - **Last Run**: Última ejecución (si ya corrió)

#### Desde el Shell de Odoo:

```python
python3 /odoo15/odoo-server/odoo-bin shell -d environmentodoo
```

Luego en Python:

```python
# Buscar el cron
cron = env['ir.cron'].search([('name', '=', 'Cloud Storage: Automatic Sync')], limit=1)
print(f"Cron ID: {cron.id}")
print(f"Active: {cron.active}")
print(f"Next Run: {cron.nextcall}")
print(f"Last Run: {cron.lastcall}")
print(f"Code: {cron.code}")

# Ver configuraciones con auto_sync activo
configs = env['cloud_storage.config'].search([
    ('is_active', '=', True),
    ('auto_sync', '=', True)
])
print(f"\nConfiguraciones con auto_sync activo: {len(configs)}")
for config in configs:
    print(f"  - {config.name}")
    print(f"    Auth: {config.auth_id.name} (state: {config.auth_id.state})")
    print(f"    Models: {len(config.model_config_ids.filtered('is_active'))}")
    print(f"    File types: {len(config.file_type_ids.filtered('is_active'))}")
```

### 3. Ejecutar el Cron Manualmente (desde código)

#### Método 1: Desde el Shell de Odoo

```python
python3 /odoo15/odoo-server/odoo-bin shell -d environmentodoo
```

Luego:

```python
# Ejecutar automatic_sync directamente
sync_service = env['cloud_storage.sync.service']
result = sync_service.automatic_sync(batch_limit=50)
print(f"Resultado: {result}")

# Ver logs recientes
logs = env['cloud_storage.sync.log'].search([
    ('sync_type', '=', 'automatic')
], limit=10, order='sync_date desc')

print("\nLogs recientes del auto sync:")
for log in logs:
    print(f"  {log.sync_date} | {log.status} | {log.file_name}")
    if log.error_message:
        print(f"    Error: {log.error_message}")
```

#### Método 2: Forzar ejecución del cron

```python
# Buscar y ejecutar el cron inmediatamente
cron = env['ir.cron'].search([('name', '=', 'Cloud Storage: Automatic Sync')], limit=1)
cron.method_direct_trigger()  # Ejecuta el cron ahora mismo
```

### 4. Ver Logs del Cron

#### Opción A: Desde la interfaz web

1. Ve a **Cloud Storage > Operations > Sync Logs**
2. Filtra por:
   - **Sync Type** = `automatic`
   - **Sync Date** = Últimas 24 horas

#### Opción B: Desde el sistema

```bash
# Ver logs del servidor de Odoo
tail -f /var/log/odoo/odoo15-server.log | grep "AUTO_SYNC"

# Ver logs recientes con contexto
grep -i "AUTO_SYNC" /var/log/odoo/odoo15-server.log | tail -100
```

#### Opción C: Desde SQL (directo a la BD)

```bash
psql -U odoo -d environmentodoo
```

```sql
-- Ver logs recientes del auto sync
SELECT
    sync_date,
    status,
    file_name,
    model_name,
    error_message
FROM cloud_storage_sync_log
WHERE sync_type = 'automatic'
ORDER BY sync_date DESC
LIMIT 20;

-- Ver resumen de última sesión
SELECT
    status,
    COUNT(*) as cantidad,
    SUM(file_size_bytes)/1024/1024 as total_mb
FROM cloud_storage_sync_log
WHERE sync_type = 'automatic'
    AND sync_date > NOW() - INTERVAL '24 hours'
GROUP BY status;
```

### 5. Cambiar Horario del Cron

Si quieres que se ejecute a una hora específica:

#### Opción A: Desde la interfaz

1. Ve a **Settings > Technical > Automation > Scheduled Actions**
2. Busca: **"Cloud Storage: Automatic Sync"**
3. Edita el campo **"Next Execution Date"** a la fecha/hora deseada
4. El sistema calculará las siguientes ejecuciones basándose en esa hora

#### Opción B: Desde el Shell

```python
from datetime import datetime, time

# Buscar el cron
cron = env['ir.cron'].search([('name', '=', 'Cloud Storage: Automatic Sync')], limit=1)

# Configurar para que se ejecute mañana a las 3 AM
tomorrow_3am = datetime.combine(
    datetime.now().date() + timedelta(days=1),
    time(3, 0, 0)
)

cron.nextcall = tomorrow_3am
print(f"Próxima ejecución programada para: {cron.nextcall}")
```

### 6. Verificación de Requisitos

Para que el auto sync funcione correctamente, verifica:

#### ✅ Configuración activa

```python
config = env['cloud_storage.config'].search([('is_active', '=', True)], limit=1)
print(f"Config activa: {config.name}")
print(f"Auto sync: {config.auto_sync}")
```

#### ✅ Autenticación válida

```python
auth = config.auth_id
print(f"Auth state: {auth.state}")
print(f"Has access token: {bool(auth.access_token)}")
print(f"Has refresh token: {bool(auth.refresh_token)}")

# Probar token
try:
    token = auth._get_valid_token()
    print(f"✅ Token válido")
except Exception as e:
    print(f"❌ Error con token: {e}")
```

#### ✅ Modelos configurados

```python
model_configs = config.model_config_ids.filtered('is_active')
print(f"Modelos activos: {len(model_configs)}")
for mc in model_configs:
    print(f"  - {mc.display_name} ({mc.model_name})")
```

#### ✅ Tipos de archivo configurados

```python
file_types = config.file_type_ids.filtered('is_active')
print(f"Tipos de archivo activos: {len(file_types)}")
print(f"Extensiones: {', '.join(file_types.mapped('extension'))}")
```

#### ✅ Archivos pendientes

```python
# Contar archivos pendientes de sincronización
for model_config in model_configs:
    if model_config.model_name in env:
        attachments = env['ir.attachment'].search([
            ('res_model', '=', model_config.model_name),
            ('cloud_sync_status', 'in', ['local', 'error'])
        ])
        print(f"{model_config.display_name}: {len(attachments)} archivos pendientes")
```

### 7. Solución de Problemas Comunes

#### Problema: El cron no se ejecuta

**Verificar:**
```python
cron = env['ir.cron'].search([('name', '=', 'Cloud Storage: Automatic Sync')], limit=1)
print(f"Active: {cron.active}")
print(f"Next call: {cron.nextcall}")
```

**Solución:** Si `active = False`, activarlo:
```python
cron.active = True
```

#### Problema: No hay configuraciones con auto_sync

**Verificar:**
```python
configs = env['cloud_storage.config'].search([
    ('is_active', '=', True),
    ('auto_sync', '=', True)
])
print(f"Configs con auto_sync: {len(configs)}")
```

**Solución:** Activar auto_sync en la configuración desde la interfaz web.

#### Problema: Token expirado

**Verificar:**
```python
config = env['cloud_storage.config'].search([('is_active', '=', True)], limit=1)
auth = config.auth_id
print(f"State: {auth.state}")
print(f"Expiry: {auth.token_expiry}")
```

**Solución:**
```python
# Refrescar token manualmente
auth.refresh_access_token()
```

#### Problema: No se generan logs

**Verificar nivel de logging:**
```bash
# Ver configuración de logging en el archivo de configuración
grep log_level /etc/odoo15-1-server.conf
```

**Solución:** Asegurar que el nivel sea al menos `info`:
```ini
log_level = info
```

### 8. Mejores Prácticas

1. **Monitorear logs regularmente:**
   ```bash
   # Crear un script de monitoreo
   watch -n 60 "grep 'AUTO_SYNC' /var/log/odoo/odoo15-server.log | tail -20"
   ```

2. **Revisar sync logs semanalmente:**
   - Ve a Cloud Storage > Operations > Sync Logs
   - Filtra por errores: `status = error`
   - Revisa y corrige problemas

3. **Mantener tokens actualizados:**
   - El cron de token refresh se ejecuta cada 6 horas automáticamente
   - Revisa el estado en: Cloud Storage > Operations > Check Token Status

4. **Configurar notificaciones por email:**
   - Para errores críticos, considera agregar notificaciones por email
   - Esto se puede hacer extendiendo el método `automatic_sync()`

## Resumen de Comandos Rápidos

```bash
# Ver logs en tiempo real
tail -f /var/log/odoo/odoo15-server.log | grep AUTO_SYNC

# Ejecutar test manual (shell)
python3 /odoo15/odoo-server/odoo-bin shell -d environmentodoo -c "env['cloud_storage.sync.service'].automatic_sync(batch_limit=50)"

# Ver últimos 20 logs de auto sync
psql -U odoo -d environmentodoo -c "SELECT sync_date, status, file_name FROM cloud_storage_sync_log WHERE sync_type = 'automatic' ORDER BY sync_date DESC LIMIT 20;"

# Ver próxima ejecución del cron
psql -U odoo -d environmentodoo -c "SELECT nextcall, lastcall, active FROM ir_cron WHERE name = 'Cloud Storage: Automatic Sync';"
```

## Fecha de Creación

2025-11-07
