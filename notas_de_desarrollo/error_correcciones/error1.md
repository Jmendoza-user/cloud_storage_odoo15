File "/home/odoo/src/odoo/16.0/odoo/tools/safe_eval.py", line 399, in safe_eval
return unsafe_eval(c, globals_dict, locals_dict)
File "ir.actions.server(2398,)", line 1, in <module>
AttributeError: 'cloud_storage.config' object has no attribute 'action_global_token_status'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
File "/tmp/tmpvobfvwb4/migrations/base/tests/test_mock_crawl.py", line 333, in crawl_menu
self.mock_action(action_vals)
File "/tmp/tmpvobfvwb4/migrations/base/tests/test_mock_crawl.py", line 349, in mock_action
action = self.env[action["type"]].browse(action["id"]).run()
File "/home/odoo/src/odoo/16.0/odoo/addons/base/models/ir_actions.py", line 675, in run
res = runner(run_self, eval_context=eval_context)
File "/home/odoo/src/odoo/16.0/addons/website/models/ir_actions_server.py", line 61, in _run_action_code_multi
res = super(ServerAction, self)._run_action_code_multi(eval_context)
File "/home/odoo/src/odoo/16.0/odoo/addons/base/models/ir_actions.py", line 545, in _run_action_code_multi
safe_eval(self.code.strip(), eval_context, mode="exec", nocopy=True, filename=str(self)) # nocopy allows to return 'action'
File "/home/odoo/src/odoo/16.0/odoo/tools/safe_eval.py", line 413, in safe_eval
raise ValueError('%s: "%s" while evaluating\n%r' % (ustr(type(e)), ustr(e), expr))
ValueError: <class 'AttributeError'>: "'cloud_storage.config' object has no attribute 'action_global_token_status'" while evaluating
'model.action_global_token_status()'