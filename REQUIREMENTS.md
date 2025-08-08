# Cloud Storage - Sincronización con Google Drive

## Descripción General
Módulo para sincronizar archivos de modelos específicos de Odoo con Google Drive, incluyendo autenticación, configuración y sincronización automática/manual.

## Funcionalidades Principales

### 1. Autenticación Google Drive
- Módulo de autenticación OAuth2 para Google Drive API
- Configuración segura de credenciales
- Manejo de tokens de acceso y renovación

### 2. Configuración de Sincronización
- **Configuración de Modelos**: Seleccionar qué modelos de Odoo sincronizar
- **Tipos de Archivos**: Configurar extensiones de archivo permitidas (.pdf, .jpg, .png, etc.)
- **Filtros de Seguridad**: Solo archivos configurados se sincronizan (NO archivos esenciales de Odoo)

### 3. Proceso de Sincronización
El proceso comprende 3 pasos críticos:
1. **Subida**: Archivo físico se sube a Google Drive
2. **Redirección**: Ruta de acceso en Odoo se actualiza a la URL de Drive
3. **Eliminación**: Archivo físico se elimina del servidor local

### 4. Métodos de Sincronización

#### 4.1 Sincronización Manual
- **Botón de sincronización** en vista de administración
- **Registro visual** de archivos sincronizados en la vista
- **Log detallado**: Qué archivo, cuándo, estado del proceso

#### 4.2 Sincronización Automática (Cron)
- **Ejecución diaria** programada
- **Registro de actividad**: Log de archivos procesados
- **Notificación de errores** si la sincronización falla

### 5. Seguridad y Validación
- **Lista blanca**: Solo archivos/modelos configurados
- **Validación de extensiones**: Control estricto de tipos de archivo
- **Backup de rutas**: Registro de rutas originales antes de redirección
- **Rollback**: Capacidad de revertir sincronización si es necesario

### 6. Logging y Monitoreo
- **Registro de sincronizaciones**: Fecha, archivo, modelo, estado
- **Métricas**: Cantidad de archivos sincronizados, espacio liberado
- **Alertas**: Fallos de autenticación, errores de API

## Arquitectura Técnica

### Modelos Requeridos:
1. `cloud_storage.config` - Configuración general
2. `cloud_storage.model.config` - Configuración por modelo
3. `cloud_storage.file.type` - Tipos de archivo permitidos  
4. `cloud_storage.sync.log` - Registro de sincronizaciones
5. `cloud_storage.auth` - Credenciales y tokens

### APIs Necesarias:
- Google Drive API v3
- Google OAuth2 API

### Consideraciones Críticas:
- **NO sincronizar archivos del sistema Odoo**
- **Validar permisos antes de eliminar archivos locales**
- **Mantener integridad referencial en base de datos**
- **Manejo robusto de errores de red**

## Estado de Desarrollo

### ✅ Completado:
- **Modelos de datos**: Todos los modelos principales creados
  - `cloud_storage.auth` - Autenticación Google Drive
  - `cloud_storage.config` - Configuración de sincronización
  - `cloud_storage.model.config` - Configuración por modelo
  - `cloud_storage.file.type` - Tipos de archivo permitidos
  - `cloud_storage.sync.log` - Registro de sincronizaciones
  - `cloud_storage.sync.service` - Servicio de sincronización

- **Vistas y UI**: Interfaces completas para administración
  - Vistas de autenticación con botones de autorización y test
  - Vistas de configuración con sincronización manual
  - Vistas de logs con filtros y dashboard estadístico
  - Estructura de menús organizada por funcionalidad

- **Seguridad**: Permisos configurados para administradores y usuarios

- **Automatización**: Cron job configurado para sincronización diaria

### 🔧 Funcionalidades Principales:
- **OAuth2 Google Drive**: Autorización completa implementada
- **Configuración por modelos**: Selección de modelos y campos a sincronizar
- **Filtrado de archivos**: Solo extensiones configuradas se sincronizan
- **Sincronización manual**: Botón para ejecutar sincronización inmediata
- **Sincronización automática**: Cron job diario programado
- **Logging completo**: Registro detallado de todas las operaciones
- **Dashboard**: Estadísticas y métricas de sincronización

### 📋 Próximos Pasos:
1. Instalar dependencias Python: `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`
2. Configurar credenciales OAuth2 en Google Cloud Console
3. Instalar y configurar el módulo en Odoo
4. Realizar pruebas de sincronización

### 🔒 Características de Seguridad Implementadas:
- Solo archivos con extensiones configuradas se sincronizan
- Validación de modelos permitidos
- Registro completo de todas las operaciones
- Permisos diferenciados por grupos de usuario
- No eliminación automática del servidor local (por seguridad)

---

*Documento actualizado: 2025-07-21*
*Estado: Desarrollo inicial completado - Listo para instalación y pruebas*