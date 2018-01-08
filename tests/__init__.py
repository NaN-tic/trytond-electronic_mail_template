# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
try:
    from trytond.modules.electronic_mail_template.tests.test_electronic_mail_template import (
        suite)
except ImportError:
    from .test_electronic_mail_template import suite

__all__ = ['suite']
