def utcnow():
    from datetime import timezone, datetime
    return datetime.now(timezone.utc)
