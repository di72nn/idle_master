
import requests  # maybe replace request with urllib or something
import bs4
try:
    from ConfigParser import RawConfigParser  # python2
except ImportError:
    from configparser import RawConfigParser  # python3
import json


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


def _get_badges_page(page_number, profile_name, cookies):
    badges_page = requests.get(
        "http://steamcommunity.com/profiles/" + profile_name +
        "/badges/?p=" + str(page_number),
        cookies=cookies)
    return bs4.BeautifulSoup(badges_page.text)


def _check_authorization(page):
    return page.find("div", {"class": "user_avatar"}) is not None


def _gather_badges_data(profile_name, cookies):
    badges_data = []

    current_page = 1
    badge_pages_count = 1
    while current_page <= badge_pages_count:
        if badge_pages_count == 1:
            print("Requesting badges page")
        else:
            print("Requesting badges page {0} of {1}".format(current_page, badge_pages_count))

        badges_page_data = _get_badges_page(current_page, profile_name, cookies)

        if current_page == 1:
            if not _check_authorization(badges_page_data):
                raise Exception("Not authorized")

            links = badges_page_data.find_all("a", {"class": "pagelink"})
            if links:
                badge_pages_count = int(links[-1].text)
                print("Found {0} more page(s)".format(badge_pages_count - 1))

        print("Processing badges page")
        badges_data += badges_page_data.find_all("div", {"class": "badge_row"})

        current_page += 1

    return badges_data


def gather_badges_info(blacklist, profile_name, cookies):
    badges = []

    for badge in _gather_badges_data(profile_name, cookies):
        badge_info = dict()
        badge_info["id"] = badge.find("a", {"class": "badge_row_overlay"})["href"].rsplit("/", 2)[1]
        badge_info["title"] = badge.find("div", {"class": "badge_title"}).contents[0].strip()

        if blacklist is not None and badge_info["id"] in blacklist:
            print("Skipped badge for blacklisted game: {0}".format(badge_info["title"]))
            continue

        title_stats = badge.find("div", {"class": "badge_title_stats"})
        if title_stats:
            progress_info_data = title_stats.find("span", {"class": "progress_info_bold"})
            if not progress_info_data:
                badge_info["card_drops_remaining"] = 0
            else:
                card_drops_text = progress_info_data.text.strip()
                if "No card drops remaining" in card_drops_text:
                    badge_info["card_drops_remaining"] = 0
                else:
                    badge_info["card_drops_remaining"] = int(card_drops_text.split(" ", 1)[0])

            playtime_info = title_stats.contents[0].strip()
            if "hrs on record" in playtime_info:
                badge_info["playtime"] = float(playtime_info.split(" ", 1)[0])
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


# TODO: parse badge page

def process_and_save_badges_info():
    auth_data = _get_auth_data()
    cookies = _get_cookies(auth_data)

    badges = gather_badges_info(None, auth_data["profile_name"], cookies)

    with open("badges_dump.json", "w") as f:
        json.dump(badges, f, indent=4)

    print("Saved")


process_and_save_badges_info()
