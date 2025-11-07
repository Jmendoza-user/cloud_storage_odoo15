## Proyecto: Cloud Storage para Odoo (Google Drive)

### 1) Objetivo del proyecto
Sustituir parcialmente el almacenamiento local de adjuntos por almacenamiento en la nube (Google Drive) para reducir el volumen de la base de datos y del filestore del servidor de producción, manteniendo la funcionalidad de previsualización/descarga y controles de seguridad.

### 2) Estado actual (según revisión del código)
- Sincronización implementada en `cloud_storage.sync.service` (Google Drive API v3, `googleapiclient`).
- Filtros por extensión y por modelo (`model_config_ids`, `file_type_ids`). Límite de tamaño de 100 MB por archivo.
- Subida con `MediaIoBaseUpload` (resumable), creación opcional de carpetas por nombre y permiso de lectura pública `anyone` en los archivos subidos.
 - Subida con `MediaIoBaseUpload` (resumable), creación opcional de carpetas por nombre. Antes se asignaba permiso público `anyone`; se ha eliminado.
- Campos persistidos en `ir.attachment`: `cloud_file_id`, `cloud_storage_url` (DEPRECATED; ver nota abajo), `cloud_sync_status`, etc. Se puede limpiar `datas` (borrado local) si está activado `delete_local_after_sync`.
- Nota: `cloud_storage_url` queda deprecado para accesos; el consumo debe ser vía proxy autenticado y `cloud_file_id`.
- Vinculación a un proxy controlador propio vía URL `/cloud_storage/file/<id>` (referenciada), pensado para servir contenido de Drive cuando `datas` ya no exista.
- Reintentos básicos mediante refresco de token en `_get_google_drive_service`. Sin colas dedicadas ni backoff robusto para 429/5xx.

### 3) Viabilidad
**Viable** para reducir espacio local, especialmente si se limita a adjuntos grandes/no críticos y con controles de seguridad adecuados. Requiere completar piezas clave: cache local, robustez ante fallos/red, y gobernanza de permisos. Recomendado para volúmenes medianos/altos si se añaden las mitigaciones descritas abajo.

### 4) Latencia y rendimiento
- Acceso a archivos desde Drive añade latencia de red: RTT 50–200 ms + transferencia. Ejemplos aproximados (con 50 Mbps):
  - 1 MB: ~0.2–0.4 s
  - 5 MB: ~0.8–1.5 s
  - 20 MB: ~3–6 s
- Vistas con múltiples miniaturas/adjuntos pueden volverse perceptiblemente más lentas si cada acceso dispara una descarga.
- Subida en lotes ya incluye pausado mínimo y batching; lectura bajo demanda aún no tiene cache ni compresión específica.

Mitigaciones propuestas:
- Cache LRU local en disco para descargas del proxy (thumbnails y últimos N MB). TTL configurable y limpieza programada.
- Pre-generar y mantener miniaturas locales para imágenes (p. ej., `image_128`, `image_256`) aunque el original esté en Drive.
- Streaming con soporte de rangos en el proxy para descargas grandes (reanudación/seek para PDF/vídeo/audio). [HECHO]
- Prefetch bajo demanda en segundo plano en vistas muy consultadas (opcional).

### 5) Tolerancia a fallos y desconexión
Riesgos actuales:
- Si `delete_local_after_sync=True` y no hay conexión a Drive, la previsualización/descarga falla y el usuario ve errores/roturas visuales.
- No hay cola ni backoff exponencial para reintentos de errores transitorios (429/5xx). La tarea puede registrar error pero no reprograma con estrategia robusta.
- Caída de Drive o pérdida de token puede bloquear sincronizaciones y lecturas a través del proxy.

Soluciones:
- Mantener siempre una copia local mínima para previsualización: miniaturas/imágenes reducidas o un fragmento inicial para PDFs (p. ej., primera página rasterizada) aunque el original se borre.
- Proxy con cache en disco y política LRU/TTL para servir en modo offline parcial.
- Implementar cola de trabajos (queue_job o similar) con reintentos, backoff exponencial y circuit breaker para cortes prolongados.
- Marcar `cloud_sync_status` con estados: `local` → `processing` → `synced` → `error`, y no procesar en paralelo un mismo attachment; usar locks/markers para evitar duplicidad.
- Si el proxy detecta fallo de Drive, responder con HTTP 503 + cabeceras Retry-After y un mensaje amigable en el UI.

### 6) Seguridad y cumplimiento
Riesgos actuales:
- Se establece permiso `anyone` en Drive (público). Esto puede filtrar información sensible y elude las ACL de Odoo.
- Enlace directo de Drive podría compartirse fuera del sistema.

Soluciones:
- Evitar `anyone` y servir SIEMPRE vía proxy autenticado en Odoo, respetando ACLs y registros relacionados. El proxy autenticará al usuario y obtendrá el binario desde Drive usando credenciales del sistema (o impersonación con domain-wide delegation si se requiere multiusuario).
- Encriptar en tránsito (HTTPS) y, si aplica, cifrado en reposo gestionado por Drive; evaluar cifrado adicional de contenidos sensibles antes de subir.
- Trazabilidad: registrar accesos en el proxy (quién/qué/cuándo), auditoría exportable.

### 7) Consistencia e integridad de datos
Riesgos actuales:
- Borrado local tras subir sin verificación de integridad (no se valida checksum en Drive).
- Carpetas en Drive se crean por nombre, posible colisión si existen duplicados en rutas distintas o renombrados.
- Archivos borrados/renombrados manualmente en Drive rompen referencias.

Soluciones:
- Al subir: calcular y guardar hash (SHA-256/MD5) y tamaño; verificar respuesta de Drive y, opcionalmente, revalidar con una lectura HEAD o metadatos antes de borrar local.
- Persistir y reutilizar `folder_id` en configuración, no buscar solo por nombre; crear estructura determinista por modelo/campo y almacenar IDs.
- Tarea periódica de reconciliación que: valida existencia por `cloud_file_id`, re-subida si falta, repara metadatos, elimina permisos indebidos.

### 8) Cuotas y límites de la API
- Drive tiene límites de cuota y tasa. La sincronización completa o picos pueden provocar 429.
- Actualmente hay un `sleep(0.1)` por batch; insuficiente para picos grandes.

Soluciones:
- Implementar backoff exponencial + jitter ante 429/5xx. [HECHO]
- Presupuestar el throughput por ventana (tokens/bucket) y autorregular el rate.
- Alertas cuando se acerque a umbrales de cuota.

### 9) Costes operativos y backups
- Backups deben incluir: base de datos (metadatos y referencias) + estrategia de backup en Drive (o exportación) para DR.
- Si se borra `datas`, los backups tradicionales del filestore dejan de incluir el binario.

Soluciones:
- Documentar y automatizar backup/restore de Drive (owner, carpetas, permisos) asociado al entorno.
- Opción de “doble escritura” temporal (mantener local N días) para ventanas de recuperación.

### 10) Compatibilidad funcional en Odoo
- Algunos módulos esperan `ir.attachment.datas` disponible. Con `datas=False`, podrían fallar si no utilizan el proxy.

Soluciones:
- Parche/override del método de lectura de adjuntos usado por vistas y reportes para que, al faltar `datas`, obtenga el contenido vía proxy/servicio y, opcionalmente, lo cachee.
- Mantener miniaturas locales para que las vistas kanban/form no se vean afectadas.

### 11) Propuestas concretas de implementación
- Proxy seguro:
  - Autenticado (ACL Odoo), streaming, soporte Range, logging, cache LRU en disco (tamaño y TTL configurables), manejo de errores con 503 y Retry-After.
  - No exponer enlaces públicos de Drive; usar `cloud_file_id` y API con credenciales del sistema.
- Integridad y lifecycle:
  - Hash + tamaño antes de borrar local; estados de sincronización; locks; reintentos con backoff.
  - Reconciliación periódica y reparación de referencias. [HECHO: cron diario que verifica `cloud_file_id`, md5 y tamaño]
  - Persistir `folder_id` en configuración; crear estructura fija por modelo/campo. [PARCIAL: agregado `drive_root_folder_id` y búsqueda por padre]
- Rendimiento UX:
  - Miniaturas locales persistentes; lazy loading; límite de tamaño para cargas inmediatas; paginación.
  - Prefetch opcional para registros abiertos frecuentemente.
- Seguridad:
  - Quitar permisos `anyone` en Drive; servir todo por proxy; auditoría de accesos.
- Observabilidad:
  - Métricas: tasa de éxito, latencias p50/p95, tamaño medio, quota remaining, ratio de aciertos de cache.
  - Alertas: fallos consecutivos, 429/5xx, desconexiones, expiración de token.
  - Auditoría de accesos vía proxy (usuario, attachment, bytes, cache hit, duración). [HECHO]
  - Eliminado warning de googleapiclient discovery cache (`cache_discovery=False`). [HECHO]

### 24) Wizards de migración y restauración
- Migración entre cuentas Drive:
  - Wizard `cloud_storage.wizard.migrate` con selección de cuenta origen/destino, carpeta origen/destino, recursividad y límite.
  - Prevención: se impide origen=destino.
  - Previsualización: muestra conteo, tamaño total estimado y muestra de nombres antes de ejecutar.
- Restauración local desde carpeta:
  - Wizard `cloud_storage.wizard.restore` con selección de cuenta, carpeta, recursividad, opción de enlazar existentes y destino por defecto.
  - Previsualización: conteo, tamaño estimado y muestra antes de ejecutar.

### 15) Parámetros de configuración (sistema)
- `cloud_storage.cache_dir`: directorio de cache en disco; por defecto `/var/tmp/odoo_cloud_cache`.
- `cloud_storage.cache_ttl_seconds`: TTL de cache en segundos; por defecto `86400` (1 día).
- `cloud_storage.cache_max_size_mb`: tamaño máximo del cache en MB; por defecto `1024` (1 GB).
- `cloud_storage.drive_root_folder_id`: ID de carpeta raíz en Drive para anidar carpetas por modelo/campo (si se define).

### 16) Seguridad ampliada
- Revocar permisos públicos existentes en Drive (limpieza de ACL heredadas): tarea de reconciliación extendida o script dedicado.
- Sanitizar cabeceras de descarga: `Content-Disposition` con filename seguro; asegurar `Content-Type` coherente; evitar header injection.
- Threat model básico: usuario interno autenticado; evitar enlaces reutilizables externos; política de sesiones y expiración de tokens.
- Cifrado opcional de contenidos sensibles antes de subir (si aplica al negocio y cumplimiento).

### 17) Rendimiento y UX ampliado
- Miniaturas locales persistentes para imágenes; generación bajo demanda y mantenimiento aunque `datas` se borre.
- Streaming chunked desde Drive al cliente (passthrough con Range implementado; evaluar `iter_content` si se usa requests en otros flujos).
- UX de degradación: mensajes claros cuando Drive no esté disponible; reintentos discretos; opción de descarga diferida.

### 18) Resiliencia y colas
- Integrar cola de trabajos (p. ej. `queue_job`) para sincronización masiva, con backoff y circuit breaker.
- Limitar tasa por ventana para respetar cuotas; pausas adaptativas y consolidación de operaciones.

### 19) Integridad y estructura
- Persistir `folder_id` por modelo/campo además de `drive_root_folder_id` para evitar búsquedas por nombre.
- Reconciliación con acciones: re-subir si falta archivo, actualizar metadatos, reportar divergencias.

### 20) Observabilidad ampliada
- Dashboards de métricas: latencias p50/p95, ratio cache hit, códigos HTTP, 429/5xx, bytes servidos, top archivos.
- Alertas (mail/log) ante umbrales o fallos consecutivos.

### 21) Cumplimiento y retención
- Políticas de retención y eliminación segura; auditorías exportables.
- Respaldo/restauración de Drive: ownership, permisos y carpetas.

### 22) Pruebas y despliegue
- Benchmarks de latencia por tamaño (1/5/20/50 MB) y redes con pérdida.
- Pruebas de memoria con Range; validación de headers en navegadores comunes.
- Plan de migración y rollback para adjuntos existentes; canary releases.

### 23) Costes y cuotas
- Estimación de consumo de cuota y costes de almacenamiento/transferencia; presupuesto por mes.

### 12) Roadmap sugerido (fases)
1. Seguridad y riesgo inmediato:
   - Eliminar `anyone` en nuevas subidas y bloquear enlaces públicos existentes. [HECHO]
   - Implementar proxy autenticado básico y usarlo en todas las vistas/descargas. [HECHO]
   - Añadir cache LRU local en disco y soporte de cabecera Range en el proxy. [HECHO]
   - Verificación de integridad MD5 antes de borrar `datas`. [HECHO]
   - Persistencia de raíz en Drive para estructura estable (`drive_root_folder_id`). [HECHO (parcial)]
2. Disponibilidad y rendimiento:
   - Cache LRU local + miniaturas locales; soporte de streaming/Range en proxy.
   - Reintentos con backoff y cola de trabajos para sincronización.
3. Integridad y gobernanza:
   - Verificación de integridad (hash), reconciliación, persistencia de `folder_id`. [HECHO en parte]
   - Módulo de auditoría y métricas. [HECHO auditoría]
4. Optimización y escalado:
   - Prefetch, limitación adaptativa por cuota, mejoras UX en vistas con muchos adjuntos.

### 13) Riesgos principales y decisiones
- Riesgo de exposición de datos si se mantiene `anyone`: Mitigar deshabilitando permisos públicos y obligando proxy autenticado.
- Riesgo de indisponibilidad (Drive/red): Mitigar con cache local, reintentos y degradación controlada del servicio.
- Riesgo de pérdida de datos: Mitigar con hash/verificación antes de borrar, reconciliación y backups consistentes.
- Impacto en UX por latencia: Mitigar con miniaturas locales y cache.

### 14) Conclusión
El proyecto es viable y aporta reducción significativa de almacenamiento local. Para producción segura y estable se recomienda abordar de inmediato seguridad de permisos, cache/miniaturas locales y reintentos/colas. Con las medidas propuestas, el impacto en latencia se reduce a niveles aceptables para la mayoría de casos de uso y se elevan sustancialmente la resiliencia y la gobernanza.


