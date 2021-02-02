import unicodedata
from email.utils import getaddresses

def recipients_from_fields(email_record):
    """
    Returns a list of email addresses who are the recipients of this email

    :param email_record: Browse record of the email
    """
    recipients = []
    for field in ('to', 'cc', 'bcc'):
        mails = getattr(email_record, field)
        if mails:
            recipients.extend([a for _, a in getaddresses([mails])])
    return recipients

def unaccent(text):
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    return unicodedata.normalize('NFKD', text).encode('ASCII',
        'ignore').decode()
