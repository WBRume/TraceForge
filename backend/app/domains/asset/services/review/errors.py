"""Transport-independent failures from asset review operations."""


class ReviewError(ValueError):
    def __init__(self, status_code: int, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail if isinstance(detail, str) else str(detail))
