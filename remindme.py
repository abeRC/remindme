#!/usr/bin/env python3

# FIXME: don't log everything lol
# FIXME: allow stuff like "one minute and 30 seconds" (text and text/number representation)
# FIXME: ctrl-c doesnt work properly; fix the threading


import telegram
from telegram import ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from functools import wraps
import logging
from queue import PriorityQueue
import random, os, time, sys
from datetime import datetime
from threading import Thread

token_file = "token.txt" # File containing the API token.
reminder_queue, bot = None, None
units = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60,
"minute": 60, "minutes": 60, "h": 3600, "hour": 3600, "hours": 3600, "d": 86400, "day": 86400, "days": 86400}

def setup_logging ():
    """Setup logging for info and exceptions, both to an external log file and to stdout."""
    # Configure logging to an external file.
    FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(filename="bot_log.log", format=FORMAT, level=logging.INFO)
    
    # Create a new handler to log to console as well and add it to the root logger (which is default).
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter(FORMAT)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

def load_token ():
    """Loads the API token from a file."""

    global tok
    try:
        with open(token_file, "r") as f:
            tok = f.read().strip()
    except:
        logging.error("Invalid or missing token in token.txt.")
        exit(1)
        raise # idk how logging or threads work with exceptions so jsut to be extra sure everything dies

# Enables you to add @send_typing_action before a handler to make the bot think while it processes the request.
def send_typing_action(func):
    """Sends typing action while processing func command."""

    @wraps(func)
    def command_func(update, context, *args, **kwargs):
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.TYPING)
        return func(update, context,  *args, **kwargs)
    return command_func

@send_typing_action
def start (update : telegram.update.Update, context : telegram.ext.callbackcontext.CallbackContext):
    """Test command to check if the bot is running."""

    msg = """Greetings, human! :3"""
    logging.info(context.bot.send_message(chat_id=update.effective_chat.id, text=msg))

def is_number (s : str):
    try:
        float(s)
        return True
    except:
        return False

def is_unit (s : str):
    return s in units

def parse_timestuff (args : list, cur_time : float):
    """Tries to parse the time stuff in args.
    Returns the scheduled time, custom reminder message (if present) and diagnostic text.
    (If an error occurs, scheduled_time is returned as None.)"""

    timestuff = []
    d_time = 0
    rmdr_msg = ""
    scheduled_time = None
    try:
        previous_number = None
        stop_i = len(args)
        for i, word in enumerate(args):
            if is_number(word):
                if previous_number: # 2 numbers in a row is bad.
                    logging.error("2 numbers in a row")
                    raise Exception
                previous_number = float(word)
                timestuff.append(word)
            elif is_unit(word):
                if not previous_number:
                    previous_number = 1
                d_time += previous_number * units[word]
                if d_time > 31536000:
                    logging.error("too long")
                    raise OverflowError
                previous_number = None
                timestuff.append(word)
            else:
                stop_i = i
                break
        if not timestuff or previous_number: # Empty timestuff or unused multiplier.
            if not timestuff:
                logging.error("empty timestuff")
            if previous_number:
                logging.error("unused multiplier")
            raise Exception

        # Everything's okay if we got to this point.
        scheduled_time = int(cur_time + d_time)
        rmdr_msg = " ".join(args[stop_i :])
        msg = f"Sure! :D\nSee you in {' '.join(timestuff)}!"
    except OverflowError:
        msg = "Too long!"
    except:
        msg = "uwaaaaa I couldn't parse your request D:"
    
    return scheduled_time, rmdr_msg, msg

@send_typing_action
def notice (update : telegram.update.Update, context : telegram.ext.callbackcontext.CallbackContext):
    """Assures the user that they'll be reminded about the specified matter after the specified amount of time."""

    # Easy stuff first.
    chat_id = update.effective_chat.id
    reply_id = update.effective_message.message_id
    cur_time = update.effective_message.date.timestamp()
    try:
        user = update.effective_user.username
    except:
        user = None

    # Attempt to parse argument list.
    scheduled_time, rmdr_msg, msg = parse_timestuff(context.args, cur_time)
    if not scheduled_time:
        logging.error("Failed to parse time stuff.")
    else:
        reminder = (scheduled_time, chat_id, reply_id, rmdr_msg, user)
        reminder_queue.put(reminder)
        logging.info("Time stuff was (hopefully) successfully parsed!")

    logging.info(context.bot.send_message(chat_id=update.effective_chat.id, text=msg, reply_to_message_id=update.effective_message.message_id))  

def reminder_watch_start ():
    """Prepare to manage and execute reminders."""

    # Initialize queue and bot.
    global reminder_queue, bot
    reminder_queue = PriorityQueue()
    bot = telegram.Bot(token=tok)
    try:
        Thread(target=reminder_watch).start()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(1)


def reminder_watch (tries=5):
    """Manage reminders."""

    try:
        while True:
            if not reminder_queue.empty():
                peek_next = reminder_queue.queue[0]
                scheduled_time = peek_next[0] # Tiemstamp is the first element of the tuple.
                if time.time() >= scheduled_time:
                    logging.info("PEEK:") ### DBG
                    logging.info(peek_next) ### DBG
                    reminder_execute()
                    continue # Keep processing reminders if we got a hit.
            time.sleep(30)
    except: 
        logging.error("AAAAAAAAAAAAAAAAAAAAAA")
        logging.error(f"{tries-1} tries remaining...")
        if tries >= 1:
            reminder_watch(tries=tries-1)
        else:
            exit(1)
    
def reminder_message (msg=None, username=None):
    """Generate the message used in the reminder. If the user didn't specify custom text,
    use defaults instead."""

    callout, rest = "", "BE REMINDED!!!1"
    if username:
        callout = f"@{username}, "
    if msg:
        rest = f'"{msg}""'
    logging.info(f"message is: {callout+rest}")
    return callout + rest

def reminder_execute ():
    """Execute reminders."""

    request = reminder_queue.get()
    chat_id, reply_id, msg, user = request[1:5]
    custom_msg = reminder_message(msg, user)
    logging.info(bot.send_message(chat_id=chat_id, text=custom_msg, reply_to_message_id=reply_id))

def main ():
    """Setup Telegram API stuff and start polling updates."""
    
    setup_logging() # Ready the logs.
    load_token() # Load the API token from a file.
    reminder_watch_start() # Actually remind people about stuff.
    time.sleep(1)
    
    updater = Updater(token=tok, use_context=True) # Listen for updates.
    dispatcher = updater.dispatcher # React to them.

    # Command handlers.
    start_handler = CommandHandler('start', start)
    remindme_handler = CommandHandler('remindme', notice)

    # Dispatch handlers so they may be triggered.
    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(remindme_handler)
    
    updater.start_polling() # Start listening (non-blocking).
    logging.info("BOT IS RUNNING! :D")
    updater.idle() 

main()
exit(1)
