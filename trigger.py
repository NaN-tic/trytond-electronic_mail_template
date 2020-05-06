# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta

__all__ = ['Trigger']


class Trigger(metaclass=PoolMeta):
    __name__ = 'ir.trigger'
    email_template = fields.Many2One('electronic.mail.template', "Template")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.action.selection.append(
            ('electronic.mail.template|mail_from_trigger', "Email Template"),
            )

    @staticmethod
    def default_model():
        model = Transaction().context.get('model', None)
        if model:
            return model

    @staticmethod
    def default_action_model():
        Model = Pool().get('ir.model')

        email_trigger = Transaction().context.get('email_template', False)
        if not email_trigger:
            return

        models = Model.search(
            [('model', '=', 'electronic.mail.template')], limit=1)
        if models:
            return models[0].id
