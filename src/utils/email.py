import jinja2


async def send_email(
        to: str,
        template: jinja2.Template | str,
        **kwargs
):
    """
    Email the specified recipient with the given template and context.
    """
    # TODO:
    #  - Use a proper email sending service (e.g. AWS SES, SendGrid, etc)
    #  - Handle email sending errors (e.g. retry, log, etc)

    if isinstance(template, jinja2.Template):
        html = template.render(**kwargs)
    elif isinstance(template, str):
        html = template
    else:
        raise ValueError("Invalid template type")

    print(f"Sending email to {to} with content: {html}")
