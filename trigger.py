# -*- coding: UTF-8 -*-
#This file is part electronic_mail_template module for Tryton.
#The COPYRIGHT file at the top level of this repository contains 
#the full copyright notices and license terms.
"Trigger Extension"
from trytond.model import fields
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta

__all__ = ['Trigger']

class Trigger:
    "Extend triggers to use Email template"
    __name__ = 'ir.trigger'
    __metaclass__ = PoolMeta
    email_template = fields.Many2One(
        'electronic.mail.template', 'Template', 
        )

    @staticmethod
    def default_model():
        """If invoked from the email_template fill model
        """
        return Transaction().context.get('model', False)

    @staticmethod
    def default_action_model():
        """If invoked from the email_template fill 
        action model as email_template
        """
        Model = Pool().get('ir.model')

        email_trigger = Transaction().context.get('email_template', False)
        if not email_trigger:
            return False

        model_ids = Model.search(
            [('model', '=', 'electronic.mail.template')])
        assert len(model_ids) == 1, 'Unexpected result for model search'
        return model_ids[0].id

    @staticmethod
    def default_action_function():
        """If invoked from the email_template fill
        action function as 'mail_from_trigger'
        """
        email_trigger = Transaction().context.get('email_template', False)
        return email_trigger and 'mail_from_trigger' or False
