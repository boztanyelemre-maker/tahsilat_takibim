from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    cost_of_cash_annual: float
    late_fee_rate_annual: float


class ActionCreate(BaseModel):
    customer_no: str
    customer_name: str | None = None
    action_type: str
    note: str | None = None


class ActionOut(BaseModel):
    id: int
    customer_no: str
    customer_name: str | None
    action_type: str
    note: str | None
    status: str

    class Config:
        from_attributes = True

