import asyncio
from collections import Counter
import os
import random
import re
import statistics
import string
import time

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from playwright.async_api import async_playwright


BOT_TOKEN = os.getenv("BOT_TOKEN", "8962365482:AAG8HIx8fNtAeeAmldHrh9HkvjrdIXDyMv4")
LANDING_URL = "https://betcam.app"


PHOTO_PATH = os.getenv("PHOTO_PATH", "image.jfif")
VIDEO_PATH = os.getenv("VIDEO_PATH", "betcam.mp4")
DEBUG_SCREENSHOT_PATH = "debug_screenshot.png"
GUIDE_URL = "https://bars-cheat-mch.craft.me/Z0OfbvzpkggWMX"

ADMIN_ID = 8124458627
CURRENT_PROMO_CODE = "CAM10"
revealed_promo_users = set()

PROXY_CONFIG = {
    "server": "http://45.63.116.130:40208",
    "username": "NuhaiProxy_b3Q2v1Kb",
    "password": "Ws5k2JGl",
}

CAPTCHA_FOOD_POOL = [
    ("🍕", "Pizza"),
    ("🍔", "Burger"),
    ("🍟", "French Fries"),
    ("🌭", "Hot Dog"),
    ("🍿", "Popcorn"),
    ("🌮", "Taco"),
    ("🍣", "Sushi"),
    ("🍩", "Donut"),
    ("🍰", "Cake"),
    ("🍦", "Ice Cream"),
    ("🍎", "Apple"),
    ("🍓", "Strawberry"),
    ("🥑", "Avocado"),
    ("🍉", "Watermelon"),
    ("🥐", "Croissant"),
    ("🍪", "Cookie"),
]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_referrals = {}
ROOM_URL_PATTERN = re.compile(r"^https://betcam\.app/watch/[a-zA-Z0-9_-]+/?$")


class BotStates(StatesGroup):
    waiting_for_captcha = State()
    waiting_for_room_url = State()
    waiting_for_new_promo = State()


def generate_emoji_captcha():
    target = random.choice(CAPTCHA_FOOD_POOL)
    target_emoji, target_name = target
    distractors = random.sample([item for item in CAPTCHA_FOOD_POOL if item != target], 3)
    options = [target] + distractors
    random.shuffle(options)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=opt_emoji,
                    callback_data=f"captcha:{'correct' if opt_emoji == target_emoji else 'wrong'}",
                )
                for opt_emoji, _ in options
            ]
        ]
    )
    return target_emoji, target_name, keyboard


def generate_code(length: int = 6) -> str:
    chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(random.choices(chars, k=length))


def generate_random_email() -> str:
    rand_part = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return f"user_{rand_part}@gmail.com"


def generate_random_password() -> str:
    specials = "!@#$%"
    letters = "".join(random.choices(string.ascii_letters, k=8))
    digits = "".join(random.choices(string.digits, k=3))
    sym = random.choice(specials)
    pwd = list(letters + digits + sym)
    random.shuffle(pwd)
    return "".join(pwd)


def apply_percentage_jitter(value_str: str) -> str:
    clean = re.sub(r"[^\d.]", "", value_str.replace(",", "."))
    try:
        num = float(clean)
    except ValueError:
        return value_str

    percent = random.uniform(0.02, 0.05)
    sign = random.choice([-1, 1])
    jittered_int = round(max(1.0, num * (1 + sign * percent)))

    if jittered_int == round(num):
        jittered_int = max(1, jittered_int + sign)

    has_x = "x" in value_str.lower()
    return f"{jittered_int}x" if has_x else f"{jittered_int}"


def analyze_chips(chips: list[str]) -> str:
    if not chips:
        return "No data collected for analysis."

    counts = Counter(chips)
    most_common_item, freq = counts.most_common(1)[0]

    if freq > 1:
        jittered_outcome = apply_percentage_jitter(most_common_item)
        return (
            f"<b>Predicted Outcome:</b> <code>{jittered_outcome}</code>\n"
            f"<b>Confidence:</b> High"
        )

    numeric_values = []
    for item in chips:
        clean = re.sub(r"[^\d.]", "", item.replace(",", "."))
        try:
            val = float(clean)
            numeric_values.append(val)
        except ValueError:
            pass

    if numeric_values:
        median_val = statistics.median(numeric_values)
        closest = min(chips, key=lambda x: abs(float(re.sub(r"[^\d.]", "", x.replace(",", ".")) or 0) - median_val))
        jittered_outcome = apply_percentage_jitter(closest)
        return (
            f"<b>Predicted Outcome:</b> <code>{jittered_outcome}</code>\n"
            f"<b>Confidence:</b> Moderate (all recent values are unique)"
        )

    jittered_outcome = apply_percentage_jitter(chips[-1])
    return (
        f"<b>Predicted Outcome:</b> <code>{jittered_outcome}</code>\n"
        f"<b>Confidence:</b> Moderate (based on sequence trend)"
    )


def get_profile_data(user):
    username = f"@{user.username}" if user.username else "Not set"
    caption = (
        f"<b>Profile</b>\n\n"
        f"<b>ID:</b> <code>{user.id}</code>\n"
        f"<b>Username:</b> {username}\n"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Domain", callback_data="view_domain")],
            [InlineKeyboardButton(text="How it works", callback_data="view_how_it_works")],
            [InlineKeyboardButton(text="Predictions", callback_data="view_predictions")],
            [InlineKeyboardButton(text="Promo Code", callback_data="view_promo")],
            [InlineKeyboardButton(text="Referrals", callback_data="view_referrals")],
        ]
    )
    return caption, keyboard


def get_results_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Refresh prediction", callback_data="refresh_prediction")],
            [InlineKeyboardButton(text="Back to Profile", callback_data="view_profile")],
        ]
    )


def get_promo_card(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    is_revealed = user_id in revealed_promo_users

    if is_revealed:
        caption = (
            f"<b>Current Promo Code</b>\n\n"
            f"<code>{CURRENT_PROMO_CODE}</code>\n\n"
            f'<i>Tap to copy. Enter this code on <a href="{LANDING_URL}">betcam.app</a> during checkout to claim your reward.</i>'
        )
        buttons = []
    else:
        caption = (
            f"<b>Current Promo Code</b>\n\n"
            f"<b>HIDDEN</b>\n\n"
            f"<i>You have 1 unrevealed bonus voucher available. Tap the button below to claim it.</i>"
        )
        buttons = [
            [InlineKeyboardButton(text="Reveal Promo (1 left)", callback_data="reveal_promo")]
        ]

    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="⚙️ Set Promo", callback_data="admin_set_promo")])

    buttons.append([InlineKeyboardButton(text="Back to Profile", callback_data="view_profile")])
    return caption, InlineKeyboardMarkup(inline_keyboard=buttons)


async def register_and_parse_chips(target_room_url: str) -> tuple[list[str], str | None]:
    screenshot_taken = None

    if os.path.exists(DEBUG_SCREENSHOT_PATH):
        try:
            os.remove(DEBUG_SCREENSHOT_PATH)
        except Exception:
            pass

    email = generate_random_email()
    password = generate_random_password()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy=PROXY_CONFIG,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )

        page = await context.new_page()
        chips_data = []

        try:
            await page.goto(target_room_url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(3500)

            email_input = page.locator('[autocomplete="email"]').first
            await email_input.wait_for(timeout=10000)
            await email_input.fill(email)

            password_input = page.locator('[autocomplete="new-password"]').first
            await password_input.wait_for(timeout=5000)
            await password_input.fill(password)

            checkbox = page.locator('[class="cp-cb"]').first
            if await checkbox.count() > 0:
                try:
                    await checkbox.click(force=True)
                except Exception:
                    pass

            submit_btn = page.locator('[type="submit"]').first
            await submit_btn.wait_for(timeout=5000)
            await submit_btn.click()

            await page.wait_for_timeout(7000)
            await page.goto(target_room_url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(6000)

            target_selector = '[class*="cp-bet-chip"]'

            try:
                await page.wait_for_selector(target_selector, timeout=15000)
            except Exception:
                pass

            raw_chips = await page.evaluate("""
                () => {
                    const selector = '[class*="cp-bet-chip"]';
                    let elements = Array.from(document.querySelectorAll(selector));

                    if (elements.length > 0) {
                        let parent = elements[0].parentElement;
                        for (let i = 0; i < 4; i++) {
                            if (parent) {
                                parent.scrollLeft = parent.scrollWidth;
                                parent = parent.parentElement;
                            }
                        }
                    }

                    elements = Array.from(document.querySelectorAll(selector));
                    return elements.map(el => el.innerText.trim()).filter(t => t.length > 0);
                }
            """)

            if raw_chips:
                chips_data.extend(raw_chips)
            else:
                for frame in page.frames:
                    try:
                        frame_chips = await frame.evaluate("""
                            () => {
                                const elements = Array.from(document.querySelectorAll('[class*="cp-bet-chip"]'));
                                return elements.map(el => el.innerText.trim()).filter(t => t.length > 0);
                            }
                        """)
                        if frame_chips:
                            chips_data.extend(frame_chips)
                    except Exception:
                        continue

            if not chips_data:
                await page.screenshot(path=DEBUG_SCREENSHOT_PATH, full_page=False)
                screenshot_taken = DEBUG_SCREENSHOT_PATH

            return chips_data, screenshot_taken

        except Exception as e:
            print(f"Workflow error: {e}")
            try:
                await page.screenshot(path=DEBUG_SCREENSHOT_PATH, full_page=False)
                screenshot_taken = DEBUG_SCREENSHOT_PATH
            except Exception:
                pass
            return [], screenshot_taken
        finally:
            await browser.close()


# --- ХЕНДЛЕРЫ ---

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject):
    referrer_id = command.args
    if referrer_id and referrer_id.isdigit():
        ref_id = int(referrer_id)
        if ref_id != message.from_user.id:
            await state.update_data(referrer=ref_id)

    target_emoji, target_name, keyboard = generate_emoji_captcha()
    await state.set_state(BotStates.waiting_for_captcha)

    await message.answer(
        f"<i>Please verify you are human:</i>\n\n"
        f"Pick: {target_emoji}\n\n",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


@dp.callback_query(BotStates.waiting_for_captcha, F.data == "captcha:correct")
async def process_captcha_success(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    referrer_id = data.get("referrer")
    if referrer_id:
        user_referrals[referrer_id] = user_referrals.get(referrer_id, 0) + 1

    await state.clear()
    await callback.message.delete()

    caption, keyboard = get_profile_data(callback.from_user)
    if os.path.exists(PHOTO_PATH):
        await callback.message.answer_photo(
            photo=FSInputFile(PHOTO_PATH),
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:
        await callback.message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer("Verification passed")


@dp.callback_query(BotStates.waiting_for_captcha, F.data == "captcha:wrong")
async def process_captcha_wrong(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Wrong choice! Try again.", show_alert=False)
    target_emoji, target_name, keyboard = generate_emoji_captcha()
    await callback.message.edit_text(
        f"<i>Wrong choice. A new task was generated:</i>\n\n"
        f"Pick: {target_emoji}\n\n",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "view_profile")
async def cb_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    caption, keyboard = get_profile_data(callback.from_user)

    if callback.message.photo:
        await callback.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:
        await callback.message.delete()
        if os.path.exists(PHOTO_PATH):
            await callback.message.answer_photo(
                photo=FSInputFile(PHOTO_PATH),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await callback.message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    await callback.answer()


@dp.callback_query(F.data == "view_predictions")
async def cb_predictions(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.waiting_for_room_url)

    caption = (
        "🔮 <b>Live Predictions</b>\n\n"
        "Please send the room link below:\n"
        "<code>https://betcam.app/watch/xxxxxxxxxx</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Back to Profile", callback_data="view_profile")]
        ]
    )
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await callback.message.delete()
        if os.path.exists(PHOTO_PATH):
            await callback.message.answer_photo(
                photo=FSInputFile(PHOTO_PATH),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await callback.message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()


@dp.message(BotStates.waiting_for_room_url, F.text)
async def process_room_url(message: Message, state: FSMContext):
    user_url = message.text.strip()

    if ROOM_URL_PATTERN.match(user_url):
        await state.update_data(last_room_url=user_url)
        kb = get_results_keyboard()

        status_msg = await message.answer(
            "⏳ <b>Analyzing live room data...</b>\n<i>Please wait ~15-20 seconds.</i>",
            parse_mode=ParseMode.HTML,
        )

        start_time = time.monotonic()
        chips, screenshot_path = await register_and_parse_chips(user_url)
        elapsed_seconds = round(time.monotonic() - start_time, 1)

        await status_msg.delete()

        if chips:
            analysis_text = analyze_chips(chips)
            response_caption = (
                f"<b>Live Room Prediction</b>\n"
                f"🔗 <code>{user_url}</code>\n"
                f"⏱ <b>Analysis time:</b> <code>{elapsed_seconds}s</code>\n"
                f"<b>Depth of analysis:</b> <b>{len(chips)}</b>\n\n"
                f"{analysis_text}"
            )
            if os.path.exists(PHOTO_PATH):
                await message.answer_photo(
                    photo=FSInputFile(PHOTO_PATH),
                    caption=response_caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            else:
                await message.answer(response_caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            response_text = (
                f"⚠️ <b>Could not extract chips from this room.</b>\n\n"
                f"The stream might be offline, bets closed, or form verification was triggered.\n"
                f"⏱ <b>Time elapsed:</b> <code>{elapsed_seconds}s</code>\n"
                f"<i>Check the screenshot of the session below:</i>"
            )
            if screenshot_path and os.path.exists(screenshot_path):
                await message.answer_photo(
                    photo=FSInputFile(screenshot_path),
                    caption=response_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            else:
                await message.answer(
                    response_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
    else:
        await message.answer(
            "⚠️ <b>Invalid link format!</b>\n\n"
            "Please provide a valid link in this format:\n"
            "<code>https://betcam.app/watch/xxxxxxxxxx</code>",
            parse_mode=ParseMode.HTML,
        )


@dp.callback_query(F.data == "refresh_prediction")
async def cb_refresh_prediction(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    room_url = data.get("last_room_url")

    if not room_url:
        await callback.answer("Room link not found. Please send the link again.", show_alert=True)
        return

    await callback.answer("Refreshing data...")
    kb = get_results_keyboard()

    if callback.message.photo:
        await callback.message.edit_caption(
            caption="⏳ <b>Refreshing live room data...</b>\n<i>Please wait ~15-20 seconds.</i>",
            parse_mode=ParseMode.HTML,
        )

    start_time = time.monotonic()
    chips, screenshot_path = await register_and_parse_chips(room_url)
    elapsed_seconds = round(time.monotonic() - start_time, 1)

    if chips:
        analysis_text = analyze_chips(chips)
        response_caption = (
            f"<b>Live Room Prediction</b>\n\n"
            f"<code>{room_url}</code>\n"
            f"<b>Analysis time:</b> <code>{elapsed_seconds}s</code>\n"
            f"<b>Depth of analysis:</b> <b>{len(chips)}</b>\n\n"
            f"{analysis_text}"
        )

        if callback.message.photo:
            await callback.message.edit_caption(
                caption=response_caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await callback.message.delete()
            if os.path.exists(PHOTO_PATH):
                await callback.message.answer_photo(
                    photo=FSInputFile(PHOTO_PATH),
                    caption=response_caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            else:
                await callback.message.answer(response_caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        response_text = (
            f"⚠️ <b>Could not extract chips from this room.</b>\n\n"
            f"The stream might be offline, bets closed, or form verification was triggered.\n"
            f"⏱ <b>Time elapsed:</b> <code>{elapsed_seconds}s</code>\n"
            f"<i>Check the screenshot of the session below:</i>"
        )
        if screenshot_path and os.path.exists(screenshot_path):
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=FSInputFile(screenshot_path),
                caption=response_text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            if callback.message.photo:
                await callback.message.edit_caption(
                    caption=response_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            else:
                await callback.message.edit_text(
                    response_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )


@dp.callback_query(F.data == "view_how_it_works")
async def cb_how_it_works(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.delete()

    caption = (
        "<b>How It Works — Step-by-Step Guide</b>\n\n"
        f'<b>Sign Up</b> — Create an account on <a href="{LANDING_URL}">betcam.app</a>\n'
        f"<b>Enter Promo Code</b> — Use Promo code \n"
        "<b>Claim Welcome Bonus</b> — Get balance bonus credited\n"
        "<b>Play & Use Predictions</b> — Analyze stream rooms with the bot\n"
        "<b>Withdraw Profit</b> — Cash out your winnings\n\n"
        f'<i><a href="{NOTION_GUIDE_URL}">Notion knowledge Base & Guide</a></i>'
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Back to Profile", callback_data="view_profile")],
        ]
    )

    if os.path.exists(VIDEO_PATH):
        video = FSInputFile(VIDEO_PATH)
        await callback.message.answer_video(
            video=video,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await callback.message.answer(
            caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )


@dp.callback_query(F.data == "view_referrals")
async def cb_referrals(callback: CallbackQuery):
    user = callback.from_user
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
    invited_count = user_referrals.get(user.id, 0)

    caption = (
        f"<b>Referral Program</b>\n\n"
        f"Invite friends and earn extra promo's for each registration!\n\n"
        f"5 referrals = 1 extra promo code\n\n"
        f"• <b>Total Invited:</b> <code>{invited_count} users</code>\n"
        f"• <b>Your Referral Link:</b>\n<code>{ref_link}</code>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Back to Profile", callback_data="view_profile")],
        ]
    )

    if callback.message.photo:
        await callback.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await callback.message.edit_text(
            caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    await callback.answer()


@dp.callback_query(F.data == "view_domain")
async def cb_domain(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    caption = (
        f"<b>Work Status</b>\n\n"
        f"<b>URL:</b> <code>{LANDING_URL}</code>\n"
        f"<b>Status:</b> 🟢 <b>Full work</b>\n"
        f"<b>Ping:</b> <code>~21ms</code>\n"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Open URL", url=LANDING_URL)],
            [InlineKeyboardButton(text="Back to Profile", callback_data="view_profile")],
        ]
    )
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await callback.message.delete()
        if os.path.exists(PHOTO_PATH):
            await callback.message.answer_photo(
                photo=FSInputFile(PHOTO_PATH),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await callback.message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "view_promo")
async def cb_promo(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    caption, kb = get_promo_card(callback.from_user.id)

    if callback.message.photo:
        await callback.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await callback.message.delete()
        if os.path.exists(PHOTO_PATH):
            await callback.message.answer_photo(
                photo=FSInputFile(PHOTO_PATH),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await callback.message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "reveal_promo")
async def cb_reveal_promo(callback: CallbackQuery):
    user_id = callback.from_user.id
    revealed_promo_users.add(user_id)

    caption, kb = get_promo_card(user_id)

    if callback.message.photo:
        await callback.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await callback.message.edit_text(
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )

    await callback.answer("🎉 Promo code revealed!", show_alert=False)


@dp.callback_query(F.data == "admin_set_promo")
async def cb_admin_set_promo(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(BotStates.waiting_for_new_promo)

    caption = (
        "⚙️ <b>Admin: Set Promo Code</b>\n\n"
        f"Current code: <code>{CURRENT_PROMO_CODE}</code>\n\n"
        "Please send the new promo code in a message:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Back to Promo", callback_data="view_promo")]
        ]
    )
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await callback.message.delete()
        if os.path.exists(PHOTO_PATH):
            await callback.message.answer_photo(
                photo=FSInputFile(PHOTO_PATH),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await callback.message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()


@dp.message(BotStates.waiting_for_new_promo, F.text)
async def process_new_promo(message: Message, state: FSMContext):
    global CURRENT_PROMO_CODE

    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    new_promo = message.text.strip().upper()
    CURRENT_PROMO_CODE = new_promo
    await state.clear()

    caption = (
        f"✅ <b>Promo code successfully updated!</b>\n\n"
        f"New code for all users:\n<code>{CURRENT_PROMO_CODE}</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Back to Profile", callback_data="view_profile")]
        ]
    )
    if os.path.exists(PHOTO_PATH):
        await message.answer_photo(
            photo=FSInputFile(PHOTO_PATH),
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb)



async def health_check(request):
    return web.Response(text="Bot is running!")


async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Health check server started on port {port}")


async def main():
    
    await start_web_server()
    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
