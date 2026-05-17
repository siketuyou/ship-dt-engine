def ok(data=None, message="success"):
    return {"code": 200, "message": message, "data": data}


def fail(message="failed", code=500):
    return {"code": code, "message": message, "data": None}
