2025-10-31 05:15:56,522 12 ERROR db_3254931 odoo.addons.base.maintenance.migrations.base.testsodoo.upgrade.base.tests.test_mock_crawl: Add>
Traceback (most recent call last):
File "/home/odoo/src/odoo/15.0/odoo/tools/safe_eval.py", line 386, in safe_eval
return unsafe_eval(c, globals_dict, locals_dict)
File "", line 1, in <module>
AttributeError: 'cloud_storage.sync.service' object has no attribute 'manual_sync'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
File "/tmp/tmpw3b3rmoe/migrations/base/tests/test_mock_crawl.py", line 333, in crawl_menu
self.mock_action(action_vals)
File "/tmp/tmpw3b3rmoe/migrations/base/tests/test_mock_crawl.py", line 349, in mock_action
action = self.env[action["type"]].browse(action["id"]).run()
File "/home/odoo/src/odoo/15.0/odoo/addons/base/models/ir_actions.py", line 649, in run
res = runner(run_self, eval_context=eval_context)
File "/home/odoo/src/odoo/15.0/addons/website/models/ir_actions.py", line 61, in _run_action_code_multi
res = super(ServerAction, self)._run_action_code_multi(eval_context)
File "/home/odoo/src/odoo/15.0/odoo/addons/base/models/ir_actions.py", line 518, in _run_action_code_multi
safe_eval(self.code.strip(), eval_context, mode="exec", nocopy=True) # nocopy allows to return 'action'
File "/home/odoo/src/odoo/15.0/odoo/tools/safe_eval.py", line 402, in safe_eval
raise ValueError('%s: "%s" while evaluating\n%r' % (ustr(type(e)), ustr(e), expr))
ValueError: <class 'AttributeError'>: "'cloud_storage.sync.service' object has no attribute 'manual_sync'" while evaluating
'action = model.manual_sync()'
2025-10-31 05:15:56,522 12 INFO db_3254931 odoo.addons.base.maintenance.migrations.base.testsodoo.upgrade.base.tests.test_mock_crawl: Mock>
2025-10-31 05:15:56,525 12 ERROR db_3254931 odoo.addons.base.maintenance.migrations.base.testsodoo.upgrade.base.tests.test_mock_crawl: Add>
Traceback (most recent call last):
File "/home/odoo/src/odoo/15.0/odoo/tools/safe_eval.py", line 386, in safe_eval
return unsafe_eval(c, globals_dict, locals_dict)
File "", line 1, in <module>
AttributeError: 'cloud_storage.config' object has no attribute 'action_global_token_status'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
File "/tmp/tmpw3b3rmoe/migrations/base/tests/test_mock_crawl.py", line 333, in crawl_menu
self.mock_action(action_vals)
File "/tmp/tmpw3b3rmoe/migrations/base/tests/test_mock_crawl.py", line 349, in mock_action
action = self.env[action["type"]].browse(action["id"]).run()
File "/home/odoo/src/odoo/15.0/odoo/addons/base/models/ir_actions.py", line 649, in run
res = runner(run_self, eval_context=eval_context)
File "/home/odoo/src/odoo/15.0/addons/website/models/ir_actions.py", line 61, in _run_action_code_multi
res = super(ServerAction, self)._run_action_code_multi(eval_context)
File "/home/odoo/src/odoo/15.0/odoo/addons/base/models/ir_actions.py", line 518, in _run_action_code_multi
safe_eval(self.code.strip(), eval_context, mode="exec", nocopy=True) # nocopy allows to return 'action'
File "/home/odoo/src/odoo/15.0/odoo/tools/safe_eval.py", line 402, in safe_eval
raise ValueError('%s: "%s" while evaluating\n%r' % (ustr(type(e)), ustr(e), expr))
ValueError: <class 'AttributeError'>: "'cloud_storage.config' object has no attribute 'action_global_token_status'" while evaluating
'model.action_global_token_status()'