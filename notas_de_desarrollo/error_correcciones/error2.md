2025-10-26 07:23:04,264 18374 CRITICAL db_3247229 odoo.service.server: Failed to initialize database `db_3247229`.
Traceback (most recent call last):
File "/home/odoo/src/odoo/18.0/odoo/service/server.py", line 1361, in preload_registries
registry = Registry.new(dbname, update_module=update_module)
File "<decorator-gen-13>", line 2, in new
File "/home/odoo/src/odoo/18.0/odoo/tools/func.py", line 97, in locked
return func(inst, *args, **kwargs)
File "/home/odoo/src/odoo/18.0/odoo/modules/registry.py", line 129, in new
odoo.modules.load_modules(registry, force_demo, status, update_module)
File "/home/odoo/src/odoo/18.0/odoo/modules/loading.py", line 545, in load_modules
env['ir.model.data']._process_end(processed_modules)
File "/tmp/tmpvobfvwb4/migrations/base/0.0.0/pre-models-no-model-data-delete.py", line 108, in _process_end
return super(IrModelData, self)._process_end(modules)
File "/home/odoo/src/odoo/18.0/odoo/addons/base/models/ir_model.py", line 2659, in _process_end
self._process_end_unlink_record(record)
File "/home/odoo/src/odoo/18.0/addons/website/models/ir_model_data.py", line 35, in _process_end_unlink_record
return super()._process_end_unlink_record(record)
File "/home/odoo/src/odoo/18.0/odoo/addons/base/models/ir_model.py", line 2588, in _process_end_unlink_record
record.unlink()
File "/home/odoo/src/odoo/18.0/addons/mail/models/ir_model_fields.py", line 59, in unlink
return super().unlink()
File "/tmp/tmpvobfvwb4/migrations/base/0.0.0/pre-models-ir_model.py", line 210, in unlink
raise util.MigrationError(message)
odoo.upgrade.util.exceptions.UpgradeError: 💥 It looks like you forgot to call `util.remove_field` on the following fields: cloud_storage.access.log.write_date
2025-10-26 07:23:04,267 18374 INFO db_3247229 odoo.service.server: Initiating shutdown
2025-10-26 07:23:04,267 18374 INFO db_3247229 odoo.service.server: Hit CTRL-C again or send a se