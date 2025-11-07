# -*- coding: utf-8 -*-

from odoo import models, fields


class CloudStorageAccessLog(models.Model):
    _name = 'cloud_storage.access.log'
    _description = 'Cloud Storage Access Log'
    _order = 'access_time desc'

    # Disable automatic audit fields to avoid migration conflicts
    # We use access_time as the primary timestamp field
    _log_access = False

    user_id = fields.Many2one('res.users', 'User', required=True)
    attachment_id = fields.Many2one('ir.attachment', 'Attachment', required=True)
    access_time = fields.Datetime('Access Time', default=fields.Datetime.now, required=True)
    bytes_served = fields.Integer('Bytes Served')
    cache_hit = fields.Boolean('Cache Hit', default=False)
    http_status = fields.Integer('HTTP Status')
    duration_ms = fields.Integer('Duration (ms)')
    range_request = fields.Char('Range')
    user_agent = fields.Char('User Agent')
    ip_address = fields.Char('IP Address')








