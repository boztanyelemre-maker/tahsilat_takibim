from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    cost_of_cash_annual: float

