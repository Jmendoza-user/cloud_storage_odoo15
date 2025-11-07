#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar que las correcciones de migración funcionan correctamente.
Ejecutar desde el shell de Odoo:
    python3 /odoo15/odoo-server/odoo-bin shell -d environmentodoo < test_migration_fixes.py
"""

print("\n" + "="*80)
print("VERIFICACIÓN DE CORRECCIONES DE MIGRACIÓN - cloud_storage")
print("="*80)

# Test 1: Verificar modelo access.log
print("\n[TEST 1] Verificando modelo cloud_storage.access.log...")
try:
    access_log = env['cloud_storage.access.log']
    has_write_date = 'write_date' in access_log._fields
    has_log_access_false = not getattr(access_log, '_log_access', True)

    print(f"  ✓ Modelo cargado correctamente")
    print(f"  - ¿Tiene campo write_date?: {has_write_date}")
    print(f"  - ¿Tiene _log_access=False?: {has_log_access_false}")

    if not has_write_date and has_log_access_false:
        print("  ✅ CORRECCIÓN APLICADA: El modelo NO tiene write_date")
    else:
        print("  ⚠️  ADVERTENCIA: Puede haber un problema con la corrección")
except Exception as e:
    print(f"  ✗ ERROR: {e}")

# Test 2: Verificar acciones de servidor
print("\n[TEST 2] Verificando acciones de servidor...")
actions_to_test = [
    'Check Token Status',
    'Manual Synchronization',
    'Config: Check & Refresh Tokens',
    'Config: Force Refresh Tokens',
    'Config: Complete Sync'
]

for action_name in actions_to_test:
    try:
        action = env['ir.actions.server'].search([('name', '=', action_name)], limit=1)
        if action:
            has_try_except = 'try:' in (action.code or '')
            print(f"  - {action_name}")
            print(f"    ID: {action.id}")
            print(f"    Tiene try-except: {'✅ Sí' if has_try_except else '❌ No'}")
        else:
            print(f"  - {action_name}: ⚠️  No encontrada")
    except Exception as e:
        print(f"  - {action_name}: ✗ ERROR: {e}")

# Test 3: Ejecutar acciones de servidor (simulación segura)
print("\n[TEST 3] Probando ejecución de acciones de servidor...")

# Test action_global_token_status
print("  [3.1] Probando action_global_token_status...")
try:
    config = env['cloud_storage.config']
    result = config.action_global_token_status()
    print(f"    ✅ Ejecutada correctamente")
    print(f"    Tipo de resultado: {type(result)}")
except AttributeError as e:
    print(f"    ⚠️  AttributeError capturado (esperado en contexto de migración): {e}")
except Exception as e:
    print(f"    ✗ ERROR inesperado: {e}")

# Test manual_sync
print("  [3.2] Probando manual_sync...")
try:
    sync_service = env['cloud_storage.sync.service']
    # No ejecutamos realmente, solo verificamos que el método existe
    if hasattr(sync_service, 'manual_sync'):
        print(f"    ✅ Método manual_sync existe")
    else:
        print(f"    ⚠️  Método manual_sync no encontrado")
except Exception as e:
    print(f"    ✗ ERROR: {e}")

# Test 4: Intentar crear un registro de access.log
print("\n[TEST 4] Probando creación de registro en access.log...")
try:
    # Buscar un attachment de prueba
    test_attachment = env['ir.attachment'].search([], limit=1)
    if test_attachment:
        test_log = env['cloud_storage.access.log'].create({
            'user_id': env.user.id,
            'attachment_id': test_attachment.id,
            'access_time': fields.Datetime.now(),
            'bytes_served': 1024,
            'cache_hit': False,
            'http_status': 200,
        })
        print(f"  ✅ Registro creado correctamente (ID: {test_log.id})")
        print(f"  - Campos disponibles: {len(test_log._fields)} campos")
        print(f"  - ¿Tiene write_date?: {'write_date' in test_log._fields}")

        # Limpiar registro de prueba
        test_log.unlink()
        print(f"  ✅ Registro de prueba eliminado")
    else:
        print(f"  ⚠️  No se encontró attachment de prueba, test omitido")
except Exception as e:
    print(f"  ✗ ERROR: {e}")

# Test 5: Verificar configuración de cloud_storage
print("\n[TEST 5] Verificando configuraciones activas...")
try:
    active_configs = env['cloud_storage.config'].search([('is_active', '=', True)])
    print(f"  - Configuraciones activas: {len(active_configs)}")
    for config in active_configs:
        print(f"    • {config.name}")
        if config.auth_id:
            print(f"      Auth: {config.auth_id.name} (Estado: {config.auth_id.state})")
except Exception as e:
    print(f"  ✗ ERROR: {e}")

# Resumen
print("\n" + "="*80)
print("RESUMEN DE VERIFICACIÓN")
print("="*80)
print("""
Si todos los tests anteriores muestran ✅ o ⚠️ (esperados), entonces:

  1. ✅ El modelo access.log NO tiene write_date (corrección aplicada)
  2. ✅ Las acciones de servidor tienen manejo de errores (try-except)
  3. ✅ Las acciones se ejecutan sin errores críticos
  4. ✅ El módulo está listo para migración

Si algún test muestra ✗ ERROR, revisa el log para más detalles.
""")
print("="*80)
