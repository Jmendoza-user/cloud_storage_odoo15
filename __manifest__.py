# -*- coding: utf-8 -*-
{
    'name': "Cloud Storage",

    'summary': """
        Sincronización de archivos con Google Drive""",

    'description': """
        Módulo para sincronizar archivos de modelos específicos de Odoo con Google Drive.
        Incluye autenticación OAuth2, configuración de modelos y tipos de archivo,
        sincronización manual y automática con logging completo.
    """,

    'author': "Custom Development",
    'website': "http://www.yourcompany.com",

    'category': 'Technical',
    'version': '1.0.0',

    'depends': ['base', 'web'],

    'external_dependencies': {
        'python': ['requests']
    },

    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/auth_views.xml',
        'views/actions.xml',
        'views/config_views.xml',
        'views/sync_log_views.xml',
        'views/menu_views.xml',
    ],
    
    'assets': {
        'web.assets_backend': [
            'cloud_storage/static/src/css/auth_form.css',
        ],
    },

    'demo': [
        'demo/demo.xml',
    ],

    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
