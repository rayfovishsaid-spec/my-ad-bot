from aiogram.fsm.state import State, StatesGroup


class CreateCampaignFSM(StatesGroup):
    choosing_type = State()
    entering_title = State()
    entering_description = State()
    entering_url = State()
    entering_channel = State()
    entering_price = State()
    entering_qty = State()


class PaymentFSM(StatesGroup):
    entering_stars_amount = State()
    entering_sbp_deposit_amount = State()
    entering_withdraw_amount = State()
    entering_withdraw_requisites = State()
    entering_reinvest_amount = State()


class PartnerVoucherFSM(StatesGroup):
    entering_amount_per_use = State()
    entering_max_uses = State()
    entering_claim_code = State()


class AdminFSM(StatesGroup):
    entering_broadcast_text = State()
    entering_setting_value = State()
