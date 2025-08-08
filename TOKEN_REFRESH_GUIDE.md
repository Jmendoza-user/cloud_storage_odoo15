# Guía de Refresco de Tokens - Cloud Storage

## Problema Resuelto

Antes, cuando el token de conexión con Google Drive se vencía, tenías que eliminar el registro de autenticación y volverlo a crear. Ahora puedes refrescar el token naturalmente sin perder la configuración.

## Nuevas Funcionalidades

### 1. Botones en la Vista de Autenticación

En la vista de configuración de autenticación (`Google Drive Auth`), ahora tienes:

- **Check Token Status**: Verifica el estado actual del token y muestra cuánto tiempo queda hasta que expire
- **Refresh Token**: Refresca manualmente el token de acceso

### 2. Botones en la Vista de Configuración

En la vista de configuración de sincronización (`Sync Configuration`), ahora tienes:

- **Check & Refresh Tokens**: Verifica y refresca automáticamente todos los tokens de configuraciones activas
- **Force Refresh Tokens**: Fuerza el refresco de todos los tokens sin importar si están expirados

### 3. Menú de Operaciones

En el menú `Cloud Storage > Operations`, ahora tienes:

- **Check Token Status**: Acceso rápido para verificar el estado de todos los tokens

### 4. Cron Job Automático

Se ha configurado un cron job que se ejecuta cada 6 horas para verificar y refrescar automáticamente los tokens.

## Cómo Usar

### Verificar Estado del Token

1. Ve a `Cloud Storage > Google Drive Auth`
2. Selecciona tu configuración de autenticación
3. Haz clic en **Check Token Status**
4. Verás una notificación con el estado actual del token

### Refrescar Token Manualmente

1. Ve a `Cloud Storage > Google Drive Auth`
2. Selecciona tu configuración de autenticación
3. Haz clic en **Refresh Token**
4. Verás una notificación confirmando el refresco

### Verificar Todos los Tokens

1. Ve a `Cloud Storage > Operations > Check Token Status`
2. O ve a `Cloud Storage > Sync Configuration` y haz clic en **Check & Refresh Tokens**
3. Verás un reporte detallado del estado de todos los tokens

### Refresco Automático

Los tokens se refrescan automáticamente:
- Cuando están a punto de expirar (5 minutos antes)
- Cada 6 horas mediante el cron job
- Cuando se intenta usar un token expirado

## Estados del Token

- **Válido**: Token activo con más de 1 hora de vida
- **Expirando pronto**: Token que expira en menos de 1 hora
- **Expirado**: Token que ya no es válido
- **Error**: Problema con el token o la configuración

## Mensajes de Notificación

### Éxito
- "Token refrescado exitosamente. Nuevo vencimiento: [fecha]"
- "Verificación completada: [X] tokens actualizados, [Y] errores"

### Advertencia
- "Token expira en [X] minutos"
- "Token expirado"

### Error
- "No hay token de refresco disponible. Necesitas reautorizar la conexión"
- "Error al refrescar el token. Verifica tu configuración"

## Logs

Todas las operaciones de token se registran en los logs de Odoo con el prefijo `cloud_storage`. Puedes ver los logs en:

- **Desarrollo**: Consola de Odoo
- **Producción**: Archivos de log del servidor

## Configuración del Cron Job

El cron job se ejecuta automáticamente cada 6 horas. Para modificar la frecuencia:

1. Ve a `Configuración > Técnico > Automatización > Cron Jobs`
2. Busca "Cloud Storage: Token Refresh"
3. Modifica el intervalo según tus necesidades

## Solución de Problemas

### Token No Se Refresca

1. Verifica que el `Client ID` y `Client Secret` sean correctos
2. Asegúrate de que el `Refresh Token` esté presente
3. Verifica la conectividad a internet
4. Revisa los logs para errores específicos

### Error de Autenticación

1. Ve a la configuración de autenticación
2. Haz clic en **Authorize** para reautorizar
3. Sigue el proceso de OAuth nuevamente

### Cron Job No Funciona

1. Verifica que el cron job esté activo
2. Revisa los logs del servidor
3. Ejecuta manualmente el cron job para probar

## Mejoras Técnicas Implementadas

1. **Validación Proactiva**: Los tokens se verifican 5 minutos antes de expirar
2. **Manejo de Errores**: Mejor manejo de errores de red y API
3. **Logging Detallado**: Logs informativos para debugging
4. **Notificaciones Inteligentes**: Mensajes claros sobre el estado de los tokens
5. **Refresco Automático**: Los tokens se refrescan automáticamente cuando se usan

## Compatibilidad

Estas mejoras son compatibles con:
- Odoo 15.0+
- Google Drive API v3
- Configuraciones existentes (no requiere reconfiguración)

## Notas Importantes

- Los tokens de acceso tienen una vida útil de 1 hora por defecto
- Los tokens de refresco no expiran a menos que se revoquen manualmente
- El sistema intenta refrescar automáticamente antes de que expire el token
- Si el refresco falla, el estado cambia a 'error' o 'expired'
