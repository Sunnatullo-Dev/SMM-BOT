from aiogram.fsm.state import State, StatesGroup


class OrderSMM(StatesGroup):
    choosing_platform = State()
    choosing_group = State()
    choosing_service = State()
    entering_link = State()
    entering_quantity = State()


class OrderState(StatesGroup):
    waiting_for_link = State()
    waiting_for_quantity = State()
    waiting_for_confirmation = State()


class BuySMS(StatesGroup):
    choosing_country = State()
    choosing_service = State()


class Deposit(StatesGroup):
    choosing_method = State()
    entering_amount = State()
    confirming_payment = State()


class AdminStates(StatesGroup):
    searching_user = State()
    searching_order = State()
    editing_user_balance = State()
    adding_balance_id = State()
    adding_balance_amount = State()
    editing_setting = State()
    editing_service_price = State()
    broadcasting = State()
    broadcast_review = State()
    adding_payment_method_name = State()
    adding_payment_method_instr = State()
    editing_payment_method_name = State()
    editing_payment_method_instr = State()
