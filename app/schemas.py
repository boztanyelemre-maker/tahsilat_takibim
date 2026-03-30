from pydantic import BaseModel, Field


class SettingsUpdate(BaseModel):
    cost_of_cash_annual: float | None = Field(
        None,
        description="Yıllık cost of cash (%) — finansal kayıp hesapları. Göndermezseniz değişmez.",
        json_schema_extra={"example": 49.0},
    )
    late_fee_rate_annual: float | None = Field(
        None,
        description="Vade farkı (tahakkuk) için yıllık oran (%). Vadesi geçmiş TRY açık bakiye × gün × (oran/100/365).",
        json_schema_extra={"example": 53.13},
    )


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

