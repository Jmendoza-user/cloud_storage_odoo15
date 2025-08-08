# Cloud Storage - Módulo de Sincronización con Google Drive para Odoo 15

[![Odoo Version](https://img.shields.io/badge/Odoo-15.0-blue.svg)](https://odoo.com/)
[![License](https://img.shields.io/badge/License-LGPL--3-green.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://python.org/)

## 📋 Descripción

Módulo avanzado para **Odoo 15** que permite sincronizar archivos de modelos específicos con **Google Drive** mediante autenticación OAuth2. Incluye sincronización manual y automática con sistema completo de logging y monitoreo.

## ✨ Características Principales

### 🔐 Autenticación OAuth2
- Integración completa con Google Drive API v3
- Configuración segura de credenciales OAuth2
- Manejo automático de tokens de acceso y renovación
- Validación de conexión con botón de prueba

### ⚙️ Configuración Avanzada
- **Configuración por Modelos**: Selecciona qué modelos de Odoo sincronizar
- **Filtrado por Extensiones**: Define tipos de archivo permitidos (.pdf, .jpg, .png, etc.)
- **Seguridad**: Solo archivos configurados se sincronizan (protege archivos del sistema)
- **Configuración Flexible**: Personaliza parámetros de sincronización

### 🔄 Métodos de Sincronización

#### Sincronización Manual
- Botón de sincronización inmediata en la interfaz de administración
- Registro visual en tiempo real de archivos sincronizados
- Control total sobre cuándo ejecutar la sincronización

#### Sincronización Automática
- **Cron Job**: Ejecución diaria programada
- **Procesamiento en Lote**: Sincroniza múltiples archivos automáticamente
- **Notificaciones**: Alertas en caso de errores

### 📊 Sistema de Logging y Monitoreo
- **Registro Detallado**: Fecha, archivo, modelo, estado de cada sincronización
- **Dashboard de Estadísticas**: Métricas de archivos procesados y espacio liberado
- **Filtros Avanzados**: Busca logs por fecha, modelo o estado
- **Alertas**: Notificaciones de fallos de autenticación o errores de API

## 🏗️ Arquitectura del Módulo

### Modelos Implementados

1. **`cloud_storage.auth`** - Gestión de autenticación OAuth2
2. **`cloud_storage.config`** - Configuración general del módulo
3. **`cloud_storage.model.config`** - Configuración específica por modelo
4. **`cloud_storage.file.type`** - Tipos de archivo permitidos
5. **`cloud_storage.sync.log`** - Registro completo de sincronizaciones
6. **`cloud_storage.sync.service`** - Servicio principal de sincronización

### Estructura de Archivos

```
cloud_storage/
├── __init__.py
├── __manifest__.py
├── README.md
├── REQUIREMENTS.md
├── controllers/
│   ├── __init__.py
│   └── controllers.py          # Controladores API
├── data/
│   └── cron_data.xml          # Configuración de tareas automáticas
├── models/
│   ├── __init__.py
│   ├── models.py              # Modelos principales
│   ├── sync_service.py        # Servicio de sincronización
│   └── ir_attachment.py       # Extensión de adjuntos
├── security/
│   └── ir.model.access.csv    # Permisos de acceso
├── static/
│   └── description/
│       └── icon.png           # Icono del módulo
└── views/
    ├── auth_views.xml         # Vistas de autenticación
    ├── config_views.xml       # Vistas de configuración
    ├── sync_log_views.xml     # Vistas de logs
    ├── menu_views.xml         # Estructura de menús
    └── templates.xml          # Plantillas web
```

## 🚀 Instalación

### Prerequisitos

1. **Odoo 15.0** instalado y funcionando
2. **Python 3.8+**
3. Acceso a **Google Cloud Console**

### Paso 1: Instalar Dependencias Python

```bash
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2 requests
```

### Paso 2: Configurar Google Cloud Console

1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuevo proyecto o selecciona uno existente
3. Habilita la **Google Drive API**
4. Crea credenciales OAuth2 para aplicación web
5. Configura las URLs de redirección autorizadas:
   ```
   http://tu-servidor-odoo:puerto/cloud_storage/oauth/callback
   ```
6. Descarga el archivo JSON con las credenciales

### Paso 3: Instalar el Módulo

1. Clona este repositorio en tu directorio de addons:
   ```bash
   git clone https://github.com/Jmendoza-user/cloud_storage_odoo15.git
   ```

2. Reinicia el servicio de Odoo

3. Ve a **Aplicaciones** → **Actualizar lista de aplicaciones**

4. Busca "Cloud Storage" e instálalo

### Paso 4: Configuración Inicial

1. Ve a **Cloud Storage** → **Configuración** → **Autenticación**
2. Sube el archivo JSON de credenciales de Google
3. Ejecuta el proceso de autorización OAuth2
4. Configura los modelos y tipos de archivo a sincronizar

## 🔧 Configuración

### Configurar Modelos para Sincronización

1. Ve a **Cloud Storage** → **Configuración** → **Configuración de Modelos**
2. Selecciona los modelos de Odoo que quieres sincronizar
3. Define los campos de archivo que se procesarán

### Configurar Tipos de Archivo

1. Ve a **Cloud Storage** → **Configuración** → **Tipos de Archivo**
2. Define las extensiones permitidas (ej: .pdf, .docx, .jpg)
3. Solo archivos con estas extensiones serán sincronizados

### Programar Sincronización Automática

El módulo incluye un cron job preconfigurado que se ejecuta diariamente. Puedes modificarlo en:
**Configuración** → **Técnico** → **Automatización** → **Acciones Programadas**

## 📖 Uso

### Sincronización Manual

1. Ve a **Cloud Storage** → **Sincronización**
2. Haz clic en **"Sincronizar Ahora"**
3. Observa el progreso en tiempo real
4. Revisa los logs para ver los resultados

### Monitoreo de Sincronización

1. Ve a **Cloud Storage** → **Logs de Sincronización**
2. Filtra por fecha, modelo o estado
3. Ve estadísticas en el dashboard
4. Identifica y soluciona posibles errores

## 🔒 Seguridad

### Características de Seguridad Implementadas

- ✅ **Lista Blanca**: Solo archivos y modelos configurados se procesan
- ✅ **Validación de Extensiones**: Control estricto de tipos de archivo
- ✅ **Registro Completo**: Todas las operaciones quedan registradas
- ✅ **Permisos Diferenciados**: Acceso controlado por grupos de usuario
- ✅ **Validación OAuth2**: Autenticación segura con Google Drive
- ✅ **No Eliminación Automática**: Los archivos locales se conservan por defecto

### Recomendaciones de Seguridad

- Mantén las credenciales OAuth2 seguras
- Revisa regularmente los logs de sincronización
- Usa HTTPS en producción
- Limita el acceso al módulo a usuarios administradores

## 🐛 Solución de Problemas

### Problemas Comunes

**Error de Autenticación OAuth2**
- Verifica que las credenciales estén correctas
- Asegúrate de que las URLs de redirección coincidan
- Regenera los tokens si es necesario

**Archivos No Se Sincronizan**
- Verifica que la extensión esté en la lista permitida
- Confirma que el modelo esté configurado
- Revisa los logs para errores específicos

**Error de Permisos**
- Verifica que el usuario tenga permisos de administrador
- Confirma los permisos de archivos en el servidor

## 📞 Soporte

Para reportar bugs o solicitar nuevas características:
- **Issues**: [GitHub Issues](https://github.com/Jmendoza-user/cloud_storage_odoo15/issues)
- **Documentación**: [Wiki del Proyecto](https://github.com/Jmendoza-user/cloud_storage_odoo15/wiki)

## 📄 Licencia

Este módulo está licenciado bajo **LGPL-3.0**. Ver [LICENSE](LICENSE) para más detalles.

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! Para contribuir:

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit tus cambios (`git commit -am 'Añadir nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Abre un Pull Request

## 📊 Estado del Proyecto

**Versión Actual**: 1.0.0  
**Estado**: ✅ Desarrollo completado - Listo para producción  
**Última Actualización**: Agosto 2025  

### Funcionalidades Completadas ✅

- [x] Autenticación OAuth2 completa
- [x] Configuración por modelos y tipos de archivo
- [x] Sincronización manual e inmediata
- [x] Sincronización automática programada
- [x] Sistema completo de logging y monitoreo
- [x] Dashboard con estadísticas
- [x] Seguridad y validaciones
- [x] Interfaz de usuario completa

### Próximas Mejoras 🔮

- [ ] Sincronización bidireccional (Google Drive → Odoo)
- [ ] Soporte para múltiples cuentas de Google Drive
- [ ] Compresión automática de archivos
- [ ] Integración con otros servicios en la nube
- [ ] API REST para integración externa

---

**Desarrollado con ❤️ para la comunidad Odoo**

*¿Te gusta este módulo? ¡Dale una ⭐ en GitHub!*