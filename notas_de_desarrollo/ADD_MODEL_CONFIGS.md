# Cómo configurar respaldos selectivos por modelo

## El problema
Tienes imágenes en `ir.attachment` pero necesitas hacer respaldo selectivo por tipo de documento (productos, contactos, etc.).

## La solución: Configurar múltiples model_configs

### Paso 1: Ve a tu configuración de Cloud Storage
**Cloud Storage > Configuration**

### Paso 2: En la pestaña "Model Configurations", agrega las siguientes configuraciones:

#### Para respaldar attachments de PRODUCTOS:
- **Model Name**: `product.product`
- **Display Name**: `Products`
- **Attachment Field**: `datas` (no importa mucho para este caso)
- **Drive Folder Name**: `Products`
- **Active**: ✓

#### Para respaldar attachments de CONTACTOS:
- **Model Name**: `res.partner`
- **Display Name**: `Partners/Contacts`
- **Attachment Field**: `image_1920`
- **Drive Folder Name**: `Partners`
- **Active**: ✓

#### Para respaldar attachments de FACTURAS:
- **Model Name**: `account.move`
- **Display Name**: `Invoices/Bills`
- **Attachment Field**: `datas`
- **Drive Folder Name**: `Invoices`
- **Active**: ✓

#### Para respaldar attachments de ÓRDENES DE VENTA:
- **Model Name**: `sale.order`
- **Display Name**: `Sale Orders`
- **Attachment Field**: `datas`
- **Drive Folder Name**: `Sales`
- **Active**: ✓

### Paso 3: Elimina la configuración de `documents.document`
Este modelo NO existe en tu instalación de Odoo 15.

## Cómo funciona

Cuando ejecutas el Quick Sync:

1. Para cada `model_config` activo (ej: `product.product`)
2. El sistema busca en `ir.attachment` WHERE `res_model = 'product.product'`
3. Solo respalda los attachments de ese modelo específico
4. Los guarda en la carpeta de Drive que configuraste

## Ejemplo SQL equivalente

```sql
-- Para product.product
SELECT * FROM ir_attachment
WHERE res_model = 'product.product'
AND type = 'binary'
AND cloud_sync_status IN ('local', 'error')
AND name ILIKE '%.jpg' OR name ILIKE '%.png' OR name ILIKE '%.jpeg';

-- Para res.partner
SELECT * FROM ir_attachment
WHERE res_model = 'res.partner'
AND type = 'binary'
AND cloud_sync_status IN ('local', 'error')
AND name ILIKE '%.jpg' OR name ILIKE '%.png' OR name ILIKE '%.jpeg';
```

## Verificar qué modelos tienes con attachments

Ejecuta desde shell de Odoo:

```python
# Ver resumen de attachments por modelo
env.cr.execute("""
    SELECT res_model, COUNT(*), SUM(file_size)/1024/1024 as mb_total
    FROM ir_attachment
    WHERE res_model IS NOT NULL
    AND type = 'binary'
    AND file_size > 0
    GROUP BY res_model
    ORDER BY mb_total DESC
    LIMIT 20
""")
print(env.cr.fetchall())
```

Esto te mostrará qué modelos tienen más attachments y cuánto pesan.

## Configuración de extensiones permitidas

No olvides también configurar en **File Types**:
- jpg ✓
- jpeg ✓
- png ✓
- pdf (si quieres respaldar PDFs también)

## Resultado esperado en los logs

Después de configurar correctamente, deberías ver:
```
[MANUAL_SYNC] Processing model: product.product with limit: 500
[MANUAL_SYNC] Found 150 attachments for product.product
[MANUAL_SYNC] Processing model: res.partner with limit: 500
[MANUAL_SYNC] Found 89 attachments for res.partner
[MANUAL_SYNC] Total files to sync: 239
```

En lugar de:
```
[MANUAL_SYNC] Processing model: documents.document with limit: 500
[MANUAL_SYNC] Found 0 files for documents.document  ❌
```
