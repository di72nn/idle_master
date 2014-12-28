import requests
try:
    import cookielib
except ImportError:
    import http.cookiejar
import bs4
import time
import subprocess
import sys
import os
import json
import logging
import datetime
import ctypes
from colorama import init, Fore

init()

os.chdir(os.path.abspath(os.path.dirname(sys.argv[0])))

message_format = "[ %(asctime)s ] %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    filename="idlemaster.log", filemode="w",
    format=message_format,
    datefmt=date_format, level=logging.DEBUG)
console = logging.StreamHandler()
console.setLevel(logging.WARNING)
console.setFormatter(logging.Formatter(message_format, date_format))
logging.getLogger('').addHandler(console)

if sys.platform.startswith('win32'):
    ctypes.windll.kernel32.SetConsoleTitleA("Idle Master")

logging.warning(Fore.GREEN + "WELCOME TO IDLE MASTER" + Fore.RESET)


def wait_for_confirmation():
    msg = "Press Enter to continue..."
    try:
        if sys.version[0] >= "3":
            input(msg)
        else:
            raw_input(msg)
    except:
        pass


try:
    settings_data = {
        "sort": "",
        "steamparental": "",
        "hasPlayTime": "false"
        }

    exec(open("./settings.txt").read(), settings_data)

    if not settings_data["sessionid"]:
        logging.warning(Fore.RED + "No sessionid set" + Fore.RESET)
        wait_for_confirmation()
        sys.exit()

    if not settings_data["steamLogin"]:
        logging.warning(Fore.RED + "No steamLogin set" + Fore.RESET)
        wait_for_confirmation()
        sys.exit()

    profile_url = "http://steamcommunity.com/profiles/" + settings_data["steamLogin"][:17]
except:
    logging.warning(Fore.RED + "Error loading config file" + Fore.RESET)
    wait_for_confirmation()
    sys.exit()


def generate_cookies():
    try:
        cookies = dict(sessionid=settings_data["sessionid"],
                       steamLogin=settings_data["steamLogin"],
                       steamparental=settings_data["steamparental"]
                       )
    except:
        logging.warning(Fore.RED + "Error setting cookies" + Fore.RESET)
        wait_for_confirmation()
        sys.exit()

    return cookies


def get_check_delay(number_of_drops_left):
    if number_of_drops_left > 1:
        check_delay = (15 * 60)
    else:
        check_delay = (5 * 60)
    return check_delay


def start_idling(app_id):
    try:
        logging.warning("Starting game " + get_app_name(app_id) + " to idle cards")
        global idling_process
        global idle_start_time

        idle_start_time = time.time()

        if sys.platform.startswith('win32'):
            idling_process = subprocess.Popen("steam-idle.exe " + str(app_id))
        elif sys.platform.startswith('darwin'):
            idling_process = subprocess.Popen(["./steam-idle", str(app_id)])
        elif sys.platform.startswith('linux'):
            idling_process = subprocess.Popen(["python", "steam-idle.py", str(app_id)])
    except:
        logging.warning(Fore.RED + "Error launching steam-idle with game ID " + str(app_id) + Fore.RESET)
        wait_for_confirmation()
        sys.exit()


def stop_idling(app_id):
    try:
        logging.warning("Closing game " + get_app_name(app_id))

        idling_process.terminate()

        total_time = int(time.time() - idle_start_time)

        logging.warning(get_app_name(app_id) + " took " + Fore.GREEN +
                        str(datetime.timedelta(seconds=total_time)) +
                        Fore.RESET + " to idle.")
    except:
        logging.warning(Fore.RED + "Error closing game. Exiting." + Fore.RESET)
        wait_for_confirmation()
        sys.exit()


def get_plain_app_name(app_id):
    try:
        api = requests.get("http://store.steampowered.com/api/appdetails/?filters=basic&appids=" + str(app_id))
        api_data = json.loads(api.text)
        return api_data[str(app_id)]["data"]["name"].encode('ascii', 'ignore').decode()
    except:
        return "App " + str(app_id)


def get_app_name(app_id):
    return Fore.CYAN + get_plain_app_name(app_id) + Fore.RESET


def get_blacklist():
    try:
        with open('blacklist.txt', 'r') as f:
            lines = f.readlines()
        blacklist = [int(n.strip()) for n in lines]
    except:
        blacklist = []

    return blacklist


logging.warning("Finding games that have card drops remaining")

cookies = generate_cookies()

def get_badges_page_data(page_number):
    try:
        badges_page = requests.get(profile_url + "/badges/?p=" + str(page_number), cookies=cookies)
        return bs4.BeautifulSoup(badges_page.text)
    except:
        logging.warning(Fore.RED + "Error reading badge page" + Fore.RESET)
        wait_for_confirmation()
        sys.exit()


badges_data = []
try:
    badges_page_data = get_badges_page_data(1)

    if not badges_page_data.find("div", {"class": "user_avatar"}):
        logging.warning(Fore.RED + "Invalid cookie data, cannot log in to Steam" + Fore.RESET)
        wait_for_confirmation()
        sys.exit()

    # TODO: check
    badge_pages_count = 0
    try:
        badge_pages_count = int(badges_page_data.find_all("a", {"class": "pagelink"})[-1].text)
    except:
        pass
    if badge_pages_count < 1:
        badge_pages_count = 1

    current_page = 1
    while current_page <= badge_pages_count:
        if badge_pages_count > 1:
            logging.warning("Processing badge page " + str(current_page) +
                            " out of " + str(badge_pages_count) + ", please wait")
        else:
            logging.warning("Processing badge page, please wait")

        badges_data += badges_page_data.find_all("div", {"class": "badge_title_stats"})

        current_page += 1
        if current_page <= badge_pages_count:
            badges_page_data = get_badges_page_data(current_page)
except:
    logging.warning(Fore.RED + "Error gathering drop info" + Fore.RESET)
    wait_for_confirmation()
    sys.exit()

blacklist = get_blacklist()
if not blacklist:
    logging.warning("No games have been blacklisted")

if settings_data["sort"] == "mostvalue" or settings_data["sort"] == "leastvalue":
    logging.warning("Getting card values, please wait...")

badges = []
for badge in badges_data:
    try:
        badge_text = badge.get_text()
        drop_count = badge.find_all("span", {"class": "progress_info_bold"})[0].contents[0]
        has_playtime = "hrs on record" in badge_text

        if ("No card drops" in drop_count or
                (not has_playtime and settings_data["hasPlayTime"].lower() == "true")):
            continue
        # Remaining drops
        remaining_drop_count, junk = drop_count.split(" ", 1)
        remaining_drop_count = int(remaining_drop_count)

        guessed_link = badge.find_parent().find_parent().find_parent().find_all("a")[0]["href"]
        junk, badge_id = guessed_link.split("/gamecards/", 1)
        badge_id = int(badge_id.replace("/", ""))
        if badge_id in blacklist:
            logging.warning(get_app_name(badge_id) + " is in blacklist, skipping game")
            continue
        else:
            push = [badge_id, remaining_drop_count, 0]

            if settings_data["sort"] == "mostvalue" or settings_data["sort"] == "leastvalue":
                game_value = requests.get(
                    "http://api.enhancedsteam.com/market_data/average_card_price/?appid=" +
                    str(badge_id) + "&cur=usd")
                push[2] = float(str(game_value.text))

            badges.append(push)
    except:
        continue

logging.warning("Found " + Fore.GREEN + str(len(badges)) + Fore.RESET + " games to idle")


def get_key(item):
    if settings_data["sort"] == "mostcards" or settings_data["sort"] == "leastcards":
        return item[1]
    elif settings_data["sort"] == "mostvalue" or settings_data["sort"] == "leastvalue":
        return item[2]
    else:
        return item[0]


possible_sort_values = ["", "mostcards", "leastcards", "mostvalue", "leastvalue"]
if settings_data["sort"] in possible_sort_values:
    if settings_data["sort"] == "":
        games = badges
    if settings_data["sort"] == "mostcards" or settings_data["sort"] == "mostvalue":
        games = sorted(badges, key=get_key, reverse=True)
    if settings_data["sort"] == "leastcards" or settings_data["sort"] == "leastvalue":
        games = sorted(badges, key=get_key, reverse=False)
else:
    logging.warning(Fore.RED + "Invalid sort value" + Fore.RESET)
    wait_for_confirmation()
    sys.exit()


def set_title(app_id, remaining_drops_count):
    if sys.platform.startswith('win32'):
        ctypes.windll.kernel32.SetConsoleTitleA(
            "Idle Master - Idling " + get_plain_app_name(app_id) +
            " [" + str(remaining_drops_count) + " remaining]")


def get_remaining_card_drops_count(app_id):
    try:
        badge = requests.get(profile_url + "/gamecards/" + str(app_id) + "/", cookies=cookies)
        badge_data = bs4.BeautifulSoup(badge.text)
        remaining_drops_string = badge_data.find_all("span", {"class": "progress_info_bold"})[0].contents[0]
        if "No card drops" in remaining_drops_string:
            return 0
        else:
            remaining_drops_count, junk = remaining_drops_string.split(" ", 1)
            return int(remaining_drops_count)
    except:
        return -1


def wait_for_server(app_id):
    still_down = True
    while still_down:
        logging.warning("Sleeping for 5 minutes.")
        try:
            time.sleep(5 * 60)
        except:
            pass
        if get_remaining_card_drops_count(app_id) >= 0:
            still_down = False
        else:
            logging.warning("Still unable to find drop info.")


for app_id, drops, value in games:
    delay = get_check_delay(int(drops))
    still_have_drops = 1
    num_cycles = 50
    max_fail = 2

    start_idling(app_id)

    logging.warning(get_app_name(app_id) + " has " + str(drops) + " card drops remaining")

    set_title(app_id, drops)

    while still_have_drops == 1:
        logging.warning("Sleeping for " + str(delay / 60) + " minutes")
        try:
            time.sleep(delay)
        except:
            pass

        num_cycles -= 1
        if num_cycles < 1:  # Sanity check against infinite loop
            still_have_drops = 0

        logging.warning("Checking to see if " + get_app_name(app_id) + " has remaining card drops")
        card_drops_left = get_remaining_card_drops_count(app_id)
        if card_drops_left == 0:
            logging.warning("No card drops remaining")
            still_have_drops = 0
        elif card_drops_left > 0:
            delay = get_check_delay(card_drops_left)
            logging.warning(get_app_name(app_id) + " has " + str(card_drops_left) + " card drops remaining")
            set_title(app_id, card_drops_left)
        else:
            if max_fail > 0:
                logging.warning("Error checking if drops are done, number of tries remaining: " + str(max_fail))
                max_fail -= 1
            else:
                # Suspend operations until Steam can be reached.
                logging.warning("Suspending operation for " + get_app_name(app_id))

                stop_idling(app_id)

                wait_for_server(app_id)

                start_idling(app_id)

                max_fail += 1
                break

    stop_idling(app_id)

    logging.warning(Fore.GREEN + "Successfully completed idling cards for " + get_app_name(app_id) + Fore.RESET)

logging.warning(Fore.GREEN + "Successfully completed idling process" + Fore.RESET)
wait_for_confirmation()
