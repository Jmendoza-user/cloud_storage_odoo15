#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar y configurar el cron de sincronización automática

Uso:
    python3 /odoo15/odoo-server/odoo-bin shell -d odooenvironment < verificar_cron.py
"""

from datetime import datetime, time, timedelta

print("\n" + "="*80)
print("VERIFICACIÓN DEL CRON DE SINCRONIZACIÓN AUTOMÁTICA")
print("="*80)

# Buscar el cron de auto sync
cron = env['ir.cron'].search([('name', '=', 'Cloud Storage: Automatic Sync')], limit=1)

if not cron:
    print("\n❌ ERROR: No se encontró el cron 'Cloud Storage: Automatic Sync'")
    print("   Ejecuta: python3 /odoo15/odoo-server/odoo-bin -c /etc/odoo15-1-server.conf -d odooenvironment -u cloud_storage --stop-after-init")
else:
    print(f"\n✅ Cron encontrado (ID: {cron.id})")
    print("\n" + "-"*80)
    print("ESTADO ACTUAL:")
    print("-"*80)
    print(f"  Nombre:              {cron.name}")
    print(f"  Activo:              {'✅ SÍ' if cron.active else '❌ NO'}")
    print(f"  Intervalo:           {cron.interval_number} {cron.interval_type}")
    print(f"  Última ejecución:    {cron.lastcall or 'Nunca'}")
    print(f"  Próxima ejecución:   {cron.nextcall or 'No configurada'}")
    print(f"  Número de llamadas:  {cron.numbercall} (-1 = infinito)")
    print(f"  Modelo:              {cron.model_id.model}")
    print(f"  Código:              {cron.code}")

    # Calcular cuándo se ejecutará
    if cron.nextcall:
        now = datetime.now()
        next_run = cron.nextcall
        delta = next_run - now

        print("\n" + "-"*80)
        print("PRÓXIMA EJECUCIÓN:")
        print("-"*80)

        if delta.total_seconds() < 0:
            print(f"  ⚠️  ¡Debió ejecutarse hace {abs(delta)} pero no lo hizo!")
        else:
            days = delta.days
            hours, remainder = divmod(delta.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            print(f"  📅 Fecha/Hora: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  ⏰ En: {days} días, {hours} horas, {minutes} minutos")

            # Verificar si es en la madrugada
            hour = next_run.hour
            if 0 <= hour <= 5:
                print(f"  ✅ Se ejecutará en la madrugada ({hour}:00 - {hour}:59)")
            else:
                print(f"  ⚠️  NO se ejecutará en la madrugada (hora: {hour}:00)")
                print(f"     Considera cambiar la hora a 3:00 AM para la madrugada")
    else:
        print("\n⚠️  No hay próxima ejecución configurada")

    # Verificar configuraciones necesarias
    print("\n" + "-"*80)
    print("CONFIGURACIONES NECESARIAS:")
    print("-"*80)

    configs_with_auto_sync = env['cloud_storage.config'].search([
        ('is_active', '=', True),
        ('auto_sync', '=', True)
    ])

    if configs_with_auto_sync:
        print(f"  ✅ {len(configs_with_auto_sync)} configuración(es) con auto_sync activo:")
        for config in configs_with_auto_sync:
            print(f"     • {config.name}")
            if config.auth_id:
                print(f"       - Auth: {config.auth_id.name} (estado: {config.auth_id.state})")
            else:
                print(f"       ⚠️  Sin autenticación configurada")
    else:
        print("  ❌ NO hay configuraciones con auto_sync activo")
        print("     El cron NO sincronizará nada aunque esté activo")

print("\n" + "="*80)
print("RECOMENDACIONES:")
print("="*80)

if not cron.active:
    print("  ❌ El cron está INACTIVO. Actívalo con:")
    print("     cron.active = True")

if not configs_with_auto_sync:
    print("  ❌ Activa auto_sync en al menos una configuración")
    print("     Ve a: Cloud Storage > Configuration > Sync Configuration")
    print("     Marca el checkbox 'Auto Sync'")

if cron.nextcall:
    hour = cron.nextcall.hour
    if not (0 <= hour <= 5):
        print(f"  ⚠️  El cron se ejecutará a las {hour}:00, no en la madrugada")
        print("     Para configurarlo a las 3:00 AM, ejecuta:")
        print("")
        print("     from datetime import datetime, time, timedelta")
        print("     cron = env['ir.cron'].search([('name', '=', 'Cloud Storage: Automatic Sync')], limit=1)")
        print("     tomorrow_3am = datetime.combine(datetime.now().date() + timedelta(days=1), time(3, 0, 0))")
        print("     cron.nextcall = tomorrow_3am")
        print("     print(f'Próxima ejecución configurada para: {cron.nextcall}')")
else:
    print("  ⚠️  No hay próxima ejecución configurada")
    print("     Configúrala para las 3:00 AM con:")
    print("")
    print("     from datetime import datetime, time, timedelta")
    print("     cron = env['ir.cron'].search([('name', '=', 'Cloud Storage: Automatic Sync')], limit=1)")
    print("     tomorrow_3am = datetime.combine(datetime.now().date() + timedelta(days=1), time(3, 0, 0))")
    print("     cron.nextcall = tomorrow_3am")
    print("     print(f'Próxima ejecución configurada para: {cron.nextcall}')")

print("\n" + "="*80)
print("COMANDOS ÚTILES:")
print("="*80)
print("  # Ver historial de ejecución (últimas 10):")
print("  env.cr.execute(\"SELECT create_date, state FROM ir_cron_trigger WHERE cron_id = %s ORDER BY create_date DESC LIMIT 10\", (cron.id,))")
print("  for row in env.cr.fetchall():")
print("      print(f'  {row[0]} - Estado: {row[1]}')")
print("")
print("  # Ejecutar el cron AHORA (para probar):")
print("  cron.method_direct_trigger()")
print("")
print("  # Ver logs recientes de auto sync:")
print("  logs = env['cloud_storage.sync.log'].search([('sync_type', '=', 'automatic')], limit=5, order='sync_date desc')")
print("  for log in logs:")
print("      print(f'{log.sync_date} | {log.status} | {log.file_name}')")
print("\n" + "="*80)
