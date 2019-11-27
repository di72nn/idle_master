
from operator import itemgetter
import time
from datetime import timedelta
import json
import sys
import subprocess
import logging
import os

import requests  # maybe replace request with urllib or something
from bs4 import BeautifulSoup
try:
    from ConfigParser import RawConfigParser  # python2
except ImportError:
    from configparser import RawConfigParser  # python3


_input = vars(__builtins__).get("raw_input", input)


FILTER_NOT_ONLY_GAMES = "not_only_games"
FILTER_NOT_ONLY_WITH_CARD_DROPS = "not_only_with_remaining_card_drops"
FILTER_WITH_PLAYTIME = "with_playtime"
SORT_MOST_REMAINING_DROPS = "most_remaining_drops"
SORT_LEAST_REMAINING_DROPS = "least_remaining_drops"
SORT_MOST_AVERAGE_CARD_PRICE = "most_avg_card_price"
SORT_LEAST_AVERAGE_CARD_PRICE = "least_avg_card_price"


class NotAuthorizedException(Exception):
    pass


def _set_working_directory():
    os.chdir(os.path.abspath(os.path.dirname(sys.argv[0])))


def _set_up_logging():
    date_format = "%Y-%m-%d %H:%M:%S"
    message_format = "%(asctime)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        filename="idle_master.log", format=message_format,
        datefmt=date_format, level=logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(message_format, date_format))

    logging.getLogger("").addHandler(ch)


def _init():
    _set_working_directory()
    _set_up_logging()


def _get_auth_data(filename="idle_master_auth_data.txt"):
    config = RawConfigParser()
    config.read(filename)

    section_name = "cookies"
    if not config.has_section(section_name):
        raise Exception("Illegal config file")
    if(not config.has_option(section_name, "sessionid") or
       not config.has_option(section_name, "steamLogin")):
        raise Exception("Session ID and/or Steam Login is/are not set")

    data = {
        "sessionid": config.get(section_name, "sessionid"),
        "steamLogin": config.get(section_name, "steamLogin")
    }
    if config.has_option(section_name, "steamparental"):
        data["steamparental"] = config.get(section_name, "steamparental")
    data["profile_name"] = data["steamLogin"][:17]
    return data


def _get_cookies(auth_data):
    return {
        "sessionid": auth_data["sessionid"],
        "steamLogin": auth_data["steamLogin"],
        "steamparental": auth_data["steamparental"]
    }


def _get_page(url, cookies=None):
    page = requests.get(url, cookies=cookies)
    return BeautifulSoup(page.text, "html.parser")


def _get_badges_page(page_number, profile_name, cookies):
    return _get_page(
        "http://steamcommunity.com/profiles/" + profile_name +
        "/badges/?p=" + str(page_number),
        cookies=cookies
    )


def _get_badge_page(game_id, profile_name, cookies):
    return _get_page(
        "http://steamcommunity.com/profiles/" + profile_name +
        "/gamecards/" + str(game_id),
        cookies=cookies
    )


def _get_game_name(game_id):
    page = requests.get("http://store.steampowered.com/api/appdetails/" +
                        "?filters=basic&appids=" + str(game_id))
    return json.loads(page.text)[str(game_id)]["data"]["name"]


def _check_authorization(page):
    return page.find("a", {"class": "user_avatar"}) is not None


def _gather_badges_data(profile_name, cookies):
    badges_data = []

    current_page = 1
    badge_pages_count = 1
    while current_page <= badge_pages_count:
        if badge_pages_count == 1:
            logging.info("Requesting badges page")
        else:
            logging.info("Requesting badges page {0} of {1}".
                         format(current_page, badge_pages_count))

        badges_page_data = _get_badges_page(current_page, profile_name, cookies)

        if not _check_authorization(badges_page_data):
            raise NotAuthorizedException("Not authorized")

        if current_page == 1:
            links = badges_page_data.find_all("a", {"class": "pagelink"})
            if links:
                badge_pages_count = int(links[-1].text)
                logging.info("Found {0} more page(s)".format(badge_pages_count - 1))

        logging.info("Processing badges page")
        badges_data += badges_page_data.find_all("div", {"class": "badge_row"})

        current_page += 1

    return badges_data


def _parse_remaining_card_drops(page_part):
    progress_info_data = page_part.find("span", {"class": "progress_info_bold"})
    if not progress_info_data:
        card_drops_remaining = None
    else:
        card_drops_text = progress_info_data.text.strip()
        if "No card drops remaining" in card_drops_text:
            card_drops_remaining = 0
        else:
            card_drops_remaining = int(card_drops_text.split(" ", 1)[0])

    return card_drops_remaining


def _get_average_card_price(game_id):
    result = requests.get(
        "http://api.enhancedsteam.com/market_data/average_card_price/" +
        "?cur=usd&appid=" + str(game_id))
    try:
        return float(result.text)
    except ValueError:
        raise Exception("Couldn't get average card price for game_id: " +
                        str(game_id))


def _generate_idle_list(badges_data, blacklist=None, whitelist=None,
                        filters=None, sort=None):
    games_only = True
    with_remaining_card_drops = True
    with_playtime = False
    if filters:
        for flt in filters:
            if flt == FILTER_NOT_ONLY_GAMES:
                games_only = False
            elif flt == FILTER_NOT_ONLY_WITH_CARD_DROPS:
                with_remaining_card_drops = False
            elif flt == FILTER_WITH_PLAYTIME:
                with_playtime = True
            else:
                raise Exception('Filter "{0}" is not supported'.format(flt))

    sort_type = None
    sort_reverse = True
    if sort:
        if sort == SORT_LEAST_REMAINING_DROPS:
            sort_type = 1
            sort_reverse = False
        elif sort == SORT_MOST_REMAINING_DROPS:
            sort_type = 1
            sort_reverse = True
        elif sort == SORT_LEAST_AVERAGE_CARD_PRICE:
            sort_type = 2
            sort_reverse = False
        elif sort == SORT_MOST_AVERAGE_CARD_PRICE:
            sort_type = 2
            sort_reverse = True
        else:
            raise Exception('Sort method "{0}" is not supported'.format(sort))

    tmp_list = [] if sort_type else None
    idle_list = []

    for badge_info in badges_data:
        if whitelist and badge_info["id"] not in whitelist:
            continue
        if blacklist and badge_info["id"] in blacklist:
            continue

        if games_only and not badge_info["is_game"]:
            continue
        if with_remaining_card_drops and not badge_info["card_drops_remaining"]:
            continue
        if with_playtime and not badge_info["playtime"]:
            continue

        if sort_type == 1:
            sort_value = badge_info["card_drops_remaining"]
        elif sort_type == 2:
            sort_value = _get_average_card_price(badge_info["id"])
        else:
            sort_value = None

        if sort_type:
            tmp_list.append((badge_info["id"], sort_value))
        else:
            idle_list.append(badge_info["id"])

    if sort_type:
        tmp_list.sort(key=itemgetter(1), reverse=sort_reverse)

        idle_list = [game_id for game_id, value in tmp_list]

    return idle_list


def _write_id_list_to_file(id_list, filename):
    with open(filename, "w") as f:
        for game_id in id_list:
            f.write("{}\n".format(game_id))


def _read_id_list_from_file(filename):
    with(open(filename)) as f:
        return [int(line.rstrip("\n")) for line in f]


def _gather_badges_info(profile_name, cookies, blacklist=None, whitelist=None):
    badges = []

    for badge in _gather_badges_data(profile_name, cookies):
        badge_info = dict()
        link = badge.find("a", {"class": "badge_row_overlay"})["href"]
        splitted = link.split("/")
        badge_info["id"] = int(splitted[6]) if len(splitted) >= 7 else -1

        if "gamecards" in link:
            is_game = True
        else:
            is_game = False
        badge_info["is_game"] = is_game

        badge_info["title"] = badge.find("div", {"class": "badge_title"}).contents[0].strip()

        if whitelist and badge_info["id"] not in whitelist:
            logging.info("Skipped badge for not whitelisted game: {0}".format(badge_info["title"]))
            continue

        if blacklist and badge_info["id"] in blacklist:
            logging.info("Skipped badge for blacklisted game: {0}".format(badge_info["title"]))
            continue

        title_stats = badge.find("div", {"class": "badge_title_stats"})
        if title_stats:
            badge_info["card_drops_remaining"] = _parse_remaining_card_drops(title_stats)

            playtime_info = title_stats.find("div", {"class": "badge_title_stats_playtime"}).string
            if "hrs on record" in playtime_info:
                badge_info["playtime"] = float(playtime_info.split(" ", 1)[0].strip())
            else:
                badge_info["playtime"] = 0
        else:
            badge_info["no_stats"] = True

        badge_progress_info = badge.find("div", {"class": "badge_progress_info"})
        cards_collected = None
        cards_total = None
        badge_ready = False
        if badge_progress_info:
            badge_progress_info_text = badge_progress_info.text.strip()
            if badge_progress_info_text:
                if " cards collected" in badge_progress_info_text:
                    splitted = badge_progress_info_text.split(" ", 3)
                    if len(splitted) > 3:  # yeah, at least 4
                        cards_collected = splitted[0]
                        cards_total = splitted[2]
                elif "Ready" in badge_progress_info_text:
                    badge_ready = True

        badge_info["cards_collected"] = cards_collected
        badge_info["cards_total"] = cards_total
        badge_info["badge_ready"] = badge_ready

        badges.append(badge_info)

    return badges


def _idle(idle_list, profile_name, cookies):
    idling = False

    index = -1
    while index < len(idle_list) - 1:
        index += 1
        game_id = idle_list[index]

        if idling:
            raise Exception("Still idling previous game, something went wrong")

        try:
            game_name = _get_game_name(game_id)
        except Exception as e:
            game_name = '<Unknown>'
            logging.warning("Exception on getting game name: {}".format(e))

        logging.info('Processing game "{0}" ({1})'.format(game_name, game_id))

        command_skip = False
        command_keep = False
        command_quit = False

        remaining_card_drops = 1000

        idling_process = None
        idle_start_time = time.time()  # not necessary
        last_idle_time = 0

        last_remaining_card_drops = 1000
        last_drop_time = time.time()
        first_time_error_occurred = time.time()
        erroneous_state = False
        erroneous_time_multiplier = 1
        while last_drop_time + 5 * 60 * 60 > time.time():
            try:
                remaining_card_drops = get_game_remaining_card_drops(
                    game_id, profile_name, cookies
                )

                if erroneous_state:
                    erroneous_state = False
                    erroneous_time_multiplier = 1
                    logging.warning("Recovered from erroneous state")
            except NotAuthorizedException:
                logging.warning("Not authorized, stopping idling")
                command_quit = True
                break
            except Exception as e:
                logging.warning("Exception on getting remaining card drops: {}".format(e))
                if not erroneous_state:
                    erroneous_state = True
                    first_time_error_occurred = time.time()
                elif first_time_error_occurred + 5 * 60 > time.time():
                    _stop_idling(idling_process)
                    idling = False
                    last_idle_time += time.time() - idle_start_time
                elif first_time_error_occurred + 24 * 60 * 60 > time.time():
                    break

            if remaining_card_drops < last_remaining_card_drops:
                if last_remaining_card_drops != 1000:
                    logging.info("Card was dropped")
                last_remaining_card_drops = remaining_card_drops
                last_drop_time = time.time()

                logging.info("Card drops remaining: {}".format(remaining_card_drops))

            if not remaining_card_drops:
                break

            if not idling:
                idling_process = _start_idling(game_id)
                idling = True
                idle_start_time = time.time()

            if erroneous_state:
                sleep_time = 60 * erroneous_time_multiplier
                erroneous_time_multiplier *= 2
            elif remaining_card_drops > 1:
                sleep_time = 10 * 60
            else:
                sleep_time = 5 * 60

            logging.info("Gonna sleep for {} seconds".format(sleep_time))
            logging.info("Press Ctrl+C to interrupt sleep and issue a command")
            try:
                time.sleep(sleep_time)
            except KeyboardInterrupt:
                logging.warning("Sleep interrupted by user")
                logging.warning(
                    "Input command and press Enter\n" +
                    " p [n] - pause for n minutes (default: 5)\n" +
                    " n - next (move current game to the end of list)\n" +
                    " s - skip (remove current game from list)\n" +
                    " q - quit\n" +
                    "(anything else - recheck remaining cards and continue idling)")
                try:
                    command = _input("> ").strip()
                except KeyboardInterrupt or EOFError:
                    command = ""

                logging.debug('Got command from user: "{}"'.format(command))
                if command.startswith("p"):
                    sleep_time = 5
                    splitted = command.split(" ")
                    if len(splitted) > 1:
                        try:
                            sleep_time = int(splitted[1])
                        except ValueError:
                            pass
                    sleep_time *= 60

                    _stop_idling(idling_process)
                    idling = False
                    last_idle_time += time.time() - idle_start_time

                    logging.info("Paused for {} seconds".format(sleep_time))
                    logging.info("Press Ctrl+C to resume")
                    try:
                        time.sleep(sleep_time)
                    except KeyboardInterrupt:
                        pass
                elif command == "n":
                    command_skip = True
                    command_keep = True
                    break
                elif command == "s":
                    command_skip = True
                    break
                elif command == "q":
                    command_quit = True
                    break

        if idling:
            _stop_idling(idling_process)
            idling = False
            last_idle_time += time.time() - idle_start_time

        if command_quit:
            break

        if not command_skip:
            if erroneous_state:
                logging.warning("Stopped idling game because of continuous errors")
            elif remaining_card_drops:
                logging.warning("Stopped idling game because drop timeout was reached")
            else:
                logging.info('Successfully finished idling "{0}", idling time: {1}'.
                             format(game_name, timedelta(seconds=last_idle_time)))

        if command_keep:
            logging.info('Moving game "{0}" ({1}) to the end of idle list'.
                         format(game_name, game_id))
        else:
            logging.info('Removing game "{0}" ({1}) from idle list'.
                         format(game_name, game_id))
        idle_list.pop(index)
        index -= 1

        if command_keep:
            idle_list.append(game_id)

        logging.info("Games left {0}".format(len(idle_list)))

    if idle_list:
        logging.info("Stopped idling list")
    else:
        logging.info("Finished idling list")

    return idle_list


def _start_idling(game_id):
    if sys.platform.startswith("win32"):
        args = ["steam-idle.exe"]
    elif sys.platform.startswith("darwin"):
        args = ["./steam-idle"]
    elif sys.platform.startswith("linux"):
        args = ["python", "steam-idle.py"]
    else:
        raise Exception("Unsupported platform: {}".format(sys.platform))
    args.append(str(game_id))

    return subprocess.Popen(args, start_new_session=True)


def _stop_idling(idling_process):
    idling_process.terminate()
    idling_process.wait()


def gather_badges_info(blacklist=None, whitelist=None):
    auth_data = _get_auth_data()
    cookies = _get_cookies(auth_data)

    return _gather_badges_info(auth_data["profile_name"], cookies,
                               blacklist=blacklist, whitelist=whitelist)


def get_game_remaining_card_drops(game_id, profile_name, cookies):
    page = _get_badge_page(game_id, profile_name, cookies)

    if not page:
        raise Exception("Error getting badge page")

    if not _check_authorization(page):
        raise NotAuthorizedException("Not authorized")

    card_drops_remaining = _parse_remaining_card_drops(page)

    if card_drops_remaining is None:
        raise Exception("Error getting remaining card drops info")

    return card_drops_remaining


def process_and_save_badges_info(filename):
    badges = gather_badges_info()

    with open(filename, "w") as f:
        json.dump(badges, f, indent=4)

    logging.info("Saved")


def generate_idle_list(
        filename=None, output_file_name=None, blacklist=None,
        whitelist=None, filters=None, sort=None):
    if filename:
        with open(filename) as f:
            badges_data = json.load(f)
    else:
        badges_data = gather_badges_info()

    idle_list = _generate_idle_list(
        badges_data, blacklist=blacklist, whitelist=whitelist,
        filters=filters, sort=sort
    )

    if output_file_name:
        _write_id_list_to_file(idle_list, output_file_name)

    return idle_list


def idle_from_file(filename):
    auth_data = _get_auth_data()
    cookies = _get_cookies(auth_data)

    idle_list = _read_id_list_from_file(filename)

    idle_list = _idle(idle_list, auth_data["profile_name"], cookies)

    _write_id_list_to_file(idle_list, filename)


# TODO: rewrite
def automatic_mode():
    idle_list_filename = "idle_list.txt"
    if not os.path.isfile(idle_list_filename):
        generate_idle_list(output_file_name=idle_list_filename)

    idle_from_file(idle_list_filename)


def main(argv):
    _init()

    automatic_mode()


if __name__ == "__main__":
    main(sys.argv)


# TODO: add command line options
# TODO: add custom exceptions and rewrite exception handling
