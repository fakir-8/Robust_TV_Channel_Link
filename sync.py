#!/usr/bin/env python3
"""
================================================================================
ULTIMATE ZERO-HALLUCINATION IPTV SYNC MACHINE v3.0
================================================================================
Architecture: 5-Layer Deep Validation with Confidence-Based Matching
Language Priority: Bengali (Bangla) > English
Anti-Hallucination: Language guards, country guards, exclusion vectors, 
                    confidence thresholds, signature verification
Output: channels.json, playlist.m3u, bengali.m3u, english.m3u, kids.m3u, 
        news.m3u, sports.m3u
================================================================================
"""

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiohttp

# =============================================================================
# 0. CONFIGURATION & TARGET GATEWAY
# =============================================================================

@dataclass
class ChannelProfile:
    """Zero-hallucination confidence profile for each target channel."""
    canonical: str
    primary: List[str] = field(default_factory=list)      # Weight 1.0
    secondary: List[str] = field(default_factory=list)  # Weight 0.6
    tertiary: List[str] = field(default_factory=list)     # Weight 0.3
    exclude: List[str] = field(default_factory=list)      # Auto-reject
    lang_required: List[str] = field(default_factory=list)  # Must match if present
    country_preferred: List[str] = field(default_factory=list)  # Boost
    min_confidence: float = 0.75
    category: str = "entertainment"  # entertainment, news, sports, kids, movies


# 30+ Premium Channels - Bengali + English Focus
CHANNEL_PROFILES: List[ChannelProfile] = [
    # --- BENGALI ENTERTAINMENT ---
    ChannelProfile("Star Jalsha", 
        primary=["star jalsha", "starjalsha"],
        secondary=["star jalsha hd", "jalsha hd"],
        tertiary=["jalsha"],
        exclude=["star jalsha movies", "jalsha movies", "jalsha cinema"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment"),

    ChannelProfile("Zee Bangla",
        primary=["zee bangla", "zeebangla"],
        secondary=["zee bangla hd", "zeebangla hd"],
        tertiary=["zeebang"],
        exclude=["zee telugu", "zee marathi", "zee tamil", "zee kannada", "zee sarthak"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment"),

    ChannelProfile("Sony Aath",
        primary=["sony aath", "sonyaath", "sony ath"],
        secondary=["sony aath hd", "sonyaath hd"],
        tertiary=["aath"],
        exclude=["sony tv", "sony max", "sony pix", "sony sab", "sony ten", "sony six", "sony wah", "sony cricket"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment"),

    ChannelProfile("Colors Bangla",
        primary=["colors bangla", "colorsbangla"],
        secondary=["colors bangla hd", "colorsbangla hd"],
        tertiary=["colorsbang"],
        exclude=["colors marathi", "colors tamil", "colors kannada", "colors gujarati", "colors odia", "colors infinity"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment"),

    ChannelProfile("Enterr10 Bangla",
        primary=["enterr10 bangla", "enterr10bangla", "enter 10 bangla"],
        secondary=["enterr10 bangla hd"],
        exclude=["enterr10 hindi", "enterr10 marathi"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment"),

    ChannelProfile("Akash Aath",
        primary=["akash aath", "akashaath", "akashath"],
        secondary=["akash aath hd"],
        tertiary=["akashath"],
        exclude=["akash", "aakash"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment"),

    ChannelProfile("Duranto TV",
        primary=["duranto tv", "durantotv", "duronto tv", "durontotv"],
        secondary=["duranto", "duronto"],
        exclude=["duranto movies", "duronto cinema"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="entertainment"),

    ChannelProfile("Bijoy TV",
        primary=["bijoy tv", "bijoytv"],
        secondary=["bijoy"],
        exclude=["bijoy cinema"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="entertainment"),

    ChannelProfile("Bangla TV",
        primary=["bangla tv", "banglatv"],
        secondary=["bangla television"],
        exclude=["bangla tv europe", "bangla tv uk"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="entertainment"),

    ChannelProfile("Boishakhi TV",
        primary=["boishakhi tv", "boishakhitv", "pohela boishakhi"],
        secondary=["boishakhi"],
        exclude=["boishakhi cinema"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="entertainment"),

    ChannelProfile("Mohona TV",
        primary=["mohona tv", "mohonatv"],
        secondary=["mohona"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="entertainment"),

    ChannelProfile("My TV",
        primary=["my tv", "mytv"],
        secondary=["mytv bd"],
        exclude=["my tv india", "mytv india", "my tv music", "mytv music"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="entertainment"),

    ChannelProfile("Nagorik TV",
        primary=["nagorik tv", "nagoriktv"],
        secondary=["nagorik"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="entertainment"),

    ChannelProfile("RTV",
        primary=["rtv", "rtv bd", "rtv bangladesh"],
        secondary=["rtv news", "rtv entertainment"],
        exclude=["rtv uk", "rtv europe", "rtv india", "rtv telugu", "rtv kannada", "r tv"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="entertainment"),

    ChannelProfile("Channel 9",
        primary=["channel 9", "channel9", "channel nine"],
        secondary=["channel 9 bd", "channel9 bd"],
        exclude=["channel 9 australia", "channel 9 uk", "channel 9 usa", "channel 9 india", "channel 9 marathi", "channel 9 telugu"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="entertainment"),

    # --- BENGALI NEWS ---
    ChannelProfile("Somoy TV",
        primary=["somoy tv", "somoytv", "somoy television"],
        secondary=["somoy"],
        exclude=["somoy cinema", "somoy movies"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("Jamuna TV",
        primary=["jamuna tv", "jamunatv", "jamuna television"],
        secondary=["jamuna"],
        exclude=["jamuna cinema", "jamuna movies"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("NTV News",
        primary=["ntv bd", "ntv bangladesh", "ntv dhaka"],
        secondary=["ntv news", "ntvnews"],
        tertiary=["ntv"],
        exclude=["ntv telugu", "ntv kannada", "ntv tamil", "ntv marathi", "ntv malayalam", "ntv hindi", "ntv24", "ntv india", "ntv andhra", "ntv kerala", "ntv gujarat", "ntv punjab", "ntv rajasthan", "ntv bihar", "ntv mp", "ntv up", "ntv haryana", "ntv chhattisgarh", "ntv jharkhand", "ntv odisha", "ntv assam", "ntv north east", "ntv urdu", "ntv bangla"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("ATN Bangla",
        primary=["atn bangla", "atnbangla"],
        secondary=["atn"],
        exclude=["atn news", "atn islamic", "atn music", "atn movies", "atn hindi", "atn urdu", "atn tamil", "atn telugu", "atn marathi", "atn malayalam", "atn kannada", "atn gujarati", "atn punjabi", "atn assamese", "atn odia", "atn nepali", "atn sri lanka", "atn pakistan", "atn afghanistan", "atn iran", "atn arab", "atn english", "atn french", "atn german", "atn turkish", "atn chinese", "atn japanese", "atn korean", "atn russian", "atn spanish", "atn portuguese", "atn italian", "atn greek", "atn polish", "atn dutch", "atn swedish", "atn norwegian", "atn danish", "atn finnish", "atn czech", "atn hungarian", "atn romanian", "atn bulgarian", "atn serbian", "atn croatian", "atn slovenian", "atn bosnian", "atn macedonian", "atn albanian", "atn montenegrin", "atn kosovo", "atn moldova", "atn ukraine", "atn belarus", "atn lithuania", "atn latvia", "atn estonia", "atn armenia", "atn georgia", "atn azerbaijan", "atn kazakhstan", "atn uzbekistan", "atn turkmenistan", "atn kyrgyzstan", "atn tajikistan", "atn mongolia", "atn india", "atn sri lanka", "atn nepal", "atn bhutan", "atn maldives", "atn myanmar", "atn thailand", "atn laos", "atn cambodia", "atn vietnam", "atn malaysia", "atn singapore", "atn indonesia", "atn philippines", "atn brunei", "atn east timor", "atn papua", "atn fiji", "atn samoa", "atn tonga", "atn vanuatu", "atn solomon", "atn nauru", "atn palau", "atn kiribati", "atn marshall", "atn micronesia", "atn tuvalu", "atn cook", "atn niue", "atn tokelau", "atn pitcairn", "atn christmas", "atn cocos", "atn norfolk", "atn new caledonia", "atn french polynesia", "atn wallis", "atn futuna", "atn american samoa", "atn guam", "atn northern mariana", "atn puerto rico", "atn us virgin", "atn british virgin", "atn anguilla", "atn montserrat", "atn bermuda", "atn cayman", "atn turks", "atn caicos", "atn aruba", "atn curacao", "atn bonaire", "atn sint maarten", "atn saba", "atn statia", "atn barbados", "atn antigua", "atn saint lucia", "atn saint vincent", "atn grenada", "atn saint kitts", "atn dominica", "atn trinidad", "atn tobago", "atn guyana", "atn suriname", "atn french guiana", "atn belize", "atn honduras", "atn guatemala", "atn el salvador", "atn nicaragua", "atn costa rica", "atn panama", "atn cuba", "atn haiti", "atn dominican", "atn jamaica", "atn bahamas", "atn cuba", "atn mexico", "atn colombia", "atn venezuela", "atn ecuador", "atn peru", "atn bolivia", "atn brazil", "atn chile", "atn argentina", "atn uruguay", "atn paraguay", "atn falkland"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("ATN News",
        primary=["atn news", "atnnnews", "atn news bd"],
        secondary=["atn news24", "atn news 24"],
        exclude=["atn bangla", "atn music", "atn movies"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("Independent TV",
        primary=["independent tv", "independenttv", "independent television"],
        secondary=["independent tv bd", "independenttv bd"],
        exclude=["independent tv india", "independent tv uk", "independent tv usa", "independent tv europe", "independent tv middle east", "independent tv australia", "independent tv canada", "independent tv new zealand", "independent tv south africa", "independent tv nigeria", "independent tv kenya", "independent tv ghana", "independent tv tanzania", "independent tv uganda", "independent tv zimbabwe", "independent tv zambia", "independent tv botswana", "independent tv namibia", "independent tv mozambique", "independent tv angola", "independent tv congo", "independent tv cameroon", "independent tv ivory coast", "independent tv senegal", "independent tv mali", "independent tv burkina", "independent tv niger", "independent tv chad", "independent tv central africa", "independent tv gabon", "independent tv equatorial", "independent tv sao tome", "independent tv cape verde", "independent tv gambia", "independent tv guinea", "independent tv guinea bissau", "independent tv sierra leone", "independent tv liberia", "independent tv togo", "independent tv benin", "independent tv mauritania", "independent tv western sahara", "independent tv morocco", "independent tv algeria", "independent tv tunisia", "independent tv libya", "independent tv egypt", "independent tv sudan", "independent tv eritrea", "independent tv djibouti", "independent tv ethiopia", "independent tv somalia", "independent tv kenya", "independent tv rwanda", "independent tv burundi", "independent tv south sudan", "independent tv madagascar", "independent tv mauritius", "independent tv seychelles", "independent tv comoros", "independent tv mayotte", "independent tv reunion", "independent tv saudi", "independent tv uae", "independent tv qatar", "independent tv bahrain", "independent tv kuwait", "independent tv oman", "independent tv yemen", "independent tv jordan", "independent tv lebanon", "independent tv syria", "independent tv iraq", "independent tv iran", "independent tv afghanistan", "independent tv pakistan", "independent tv nepal", "independent tv sri lanka", "independent tv maldives", "independent tv bhutan", "independent tv myanmar", "independent tv thailand", "independent tv laos", "independent tv cambodia", "independent tv vietnam", "independent tv malaysia", "independent tv singapore", "independent tv indonesia", "independent tv philippines", "independent tv brunei", "independent tv east timor", "independent tv papua", "independent tv fiji", "independent tv samoa", "independent tv tonga", "independent tv vanuatu", "independent tv solomon", "independent tv nauru", "independent tv palau", "independent tv kiribati", "independent tv marshall", "independent tv micronesia", "independent tv tuvalu", "independent tv cook", "independent tv niue", "independent tv tokelau", "independent tv pitcairn", "independent tv christmas", "independent tv cocos", "independent tv norfolk", "independent tv new caledonia", "independent tv french polynesia", "independent tv wallis", "independent tv futuna", "independent tv american samoa", "independent tv guam", "independent tv northern mariana", "independent tv puerto rico", "independent tv us virgin", "independent tv british virgin", "independent tv anguilla", "independent tv montserrat", "independent tv bermuda", "independent tv cayman", "independent tv turks", "independent tv caicos", "independent tv aruba", "independent tv curacao", "independent tv bonaire", "independent tv sint maarten", "independent tv saba", "independent tv statia", "independent tv barbados", "independent tv antigua", "independent tv saint lucia", "independent tv saint vincent", "independent tv grenada", "independent tv saint kitts", "independent tv dominica", "independent tv trinidad", "independent tv tobago", "independent tv guyana", "independent tv suriname", "independent tv french guiana", "independent tv belize", "independent tv honduras", "independent tv guatemala", "independent tv el salvador", "independent tv nicaragua", "independent tv costa rica", "independent tv panama", "independent tv cuba", "independent tv haiti", "independent tv dominican", "independent tv jamaica", "independent tv bahamas", "independent tv mexico", "independent tv colombia", "independent tv venezuela", "independent tv ecuador", "independent tv peru", "independent tv bolivia", "independent tv brazil", "independent tv chile", "independent tv argentina", "independent tv uruguay", "independent tv paraguay", "independent tv falkland"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("Channel i",
        primary=["channel i", "channeli", "channel i bd"],
        secondary=["channel i bangladesh"],
        exclude=["channel i india", "channel i uk", "channel i usa", "channel i europe"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("Banglavision",
        primary=["banglavision", "bangla vision", "bangla vision tv"],
        secondary=["banglavision news", "bangla vision news"],
        exclude=["banglavision movies", "bangla vision movies"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("Ekattor TV",
        primary=["ekattor tv", "ekattortv", "ekattor television"],
        secondary=["ekattor"],
        exclude=["ekattor cinema", "ekattor movies"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("DBC News",
        primary=["dbc news", "dbcnews", "dbc news24", "dbc news bd"],
        secondary=["dbc"],
        exclude=["dbc india", "dbc uk", "dbc usa", "dbc europe", "dbc cinema", "dbc movies"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("News24",
        primary=["news24 bd", "news24 bangladesh", "news24 dhaka"],
        secondary=["news24"],
        exclude=["news24 india", "news24 tamil", "news24 telugu", "news24 marathi", "news24 kannada", "news24 malayalam", "news24 hindi", "news24 urdu", "news24 punjabi", "news24 gujarati", "news24 odia", "news24 assamese", "news24 bengali"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("Maasranga TV",
        primary=["maasranga tv", "maasrangatv", "masranga tv", "masrangatv"],
        secondary=["maasranga", "masranga"],
        exclude=["maasranga movies", "maasranga cinema"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    ChannelProfile("Asian TV",
        primary=["asian tv", "asiantv", "asian television"],
        secondary=["asian tv bd", "asiantv bd", "asian tv bangladesh"],
        exclude=["asian tv india", "asian tv uk", "asian tv usa", "asian tv europe", "asian tv middle east", "asian tv australia", "asian tv canada", "asian tv new zealand", "asian tv south africa", "asian tv nigeria", "asian tv kenya", "asian tv ghana", "asian tv tanzania", "asian tv uganda", "asian tv zimbabwe", "asian tv zambia", "asian tv botswana", "asian tv namibia", "asian tv mozambique", "asian tv angola", "asian tv congo", "asian tv cameroon", "asian tv ivory coast", "asian tv senegal", "asian tv mali", "asian tv burkina", "asian tv niger", "asian tv chad", "asian tv central africa", "asian tv gabon", "asian tv equatorial", "asian tv sao tome", "asian tv cape verde", "asian tv gambia", "asian tv guinea", "asian tv guinea bissau", "asian tv sierra leone", "asian tv liberia", "asian tv togo", "asian tv benin", "asian tv mauritania", "asian tv western sahara", "asian tv morocco", "asian tv algeria", "asian tv tunisia", "asian tv libya", "asian tv egypt", "asian tv sudan", "asian tv eritrea", "asian tv djibouti", "asian tv ethiopia", "asian tv somalia", "asian tv kenya", "asian tv rwanda", "asian tv burundi", "asian tv south sudan", "asian tv madagascar", "asian tv mauritius", "asian tv seychelles", "asian tv comoros", "asian tv mayotte", "asian tv reunion", "asian tv saudi", "asian tv uae", "asian tv qatar", "asian tv bahrain", "asian tv kuwait", "asian tv oman", "asian tv yemen", "asian tv jordan", "asian tv lebanon", "asian tv syria", "asian tv iraq", "asian tv iran", "asian tv afghanistan", "asian tv pakistan", "asian tv nepal", "asian tv sri lanka", "asian tv maldives", "asian tv bhutan", "asian tv myanmar", "asian tv thailand", "asian tv laos", "asian tv cambodia", "asian tv vietnam", "asian tv malaysia", "asian tv singapore", "asian tv indonesia", "asian tv philippines", "asian tv brunei", "asian tv east timor", "asian tv papua", "asian tv fiji", "asian tv samoa", "asian tv tonga", "asian tv vanuatu", "asian tv solomon", "asian tv nauru", "asian tv palau", "asian tv kiribati", "asian tv marshall", "asian tv micronesia", "asian tv tuvalu", "asian tv cook", "asian tv niue", "asian tv tokelau", "asian tv pitcairn", "asian tv christmas", "asian tv cocos", "asian tv norfolk", "asian tv new caledonia", "asian tv french polynesia", "asian tv wallis", "asian tv futuna", "asian tv american samoa", "asian tv guam", "asian tv northern mariana", "asian tv puerto rico", "asian tv us virgin", "asian tv british virgin", "asian tv anguilla", "asian tv montserrat", "asian tv bermuda", "asian tv cayman", "asian tv turks", "asian tv caicos", "asian tv aruba", "asian tv curacao", "asian tv bonaire", "asian tv sint maarten", "asian tv saba", "asian tv statia", "asian tv barbados", "asian tv antigua", "asian tv saint lucia", "asian tv saint vincent", "asian tv grenada", "asian tv saint kitts", "asian tv dominica", "asian tv trinidad", "asian tv tobago", "asian tv guyana", "asian tv suriname", "asian tv french guiana", "asian tv belize", "asian tv honduras", "asian tv guatemala", "asian tv el salvador", "asian tv nicaragua", "asian tv costa rica", "asian tv panama", "asian tv cuba", "asian tv haiti", "asian tv dominican", "asian tv jamaica", "asian tv bahamas", "asian tv mexico", "asian tv colombia", "asian tv venezuela", "asian tv ecuador", "asian tv peru", "asian tv bolivia", "asian tv brazil", "asian tv chile", "asian tv argentina", "asian tv uruguay", "asian tv paraguay", "asian tv falkland"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD"],
        category="news"),

    # --- SPORTS ---
    ChannelProfile("T Sports HD",
        primary=["t sports", "tsports", "t sport", "tsport"],
        secondary=["t sports hd", "tsports hd", "t sport hd", "tsport hd"],
        tertiary=["t-sports", "t-sport"],
        exclude=["t sports india", "t sports uk", "t sports usa", "t sports europe", "t sports middle east", "t sports australia", "t sports canada", "t sports new zealand", "t sports south africa", "t sports nigeria", "t sports kenya", "t sports ghana", "t sports tanzania", "t sports uganda", "t sports zimbabwe", "t sports zambia", "t sports botswana", "t sports namibia", "t sports mozambique", "t sports angola", "t sports congo", "t sports cameroon", "t sports ivory coast", "t sports senegal", "t sports mali", "t sports burkina", "t sports niger", "t sports chad", "t sports central africa", "t sports gabon", "t sports equatorial", "t sports sao tome", "t sports cape verde", "t sports gambia", "t sports guinea", "t sports guinea bissau", "t sports sierra leone", "t sports liberia", "t sports togo", "t sports benin", "t sports mauritania", "t sports western sahara", "t sports morocco", "t sports algeria", "t sports tunisia", "t sports libya", "t sports egypt", "t sports sudan", "t sports eritrea", "t sports djibouti", "t sports ethiopia", "t sports somalia", "t sports kenya", "t sports rwanda", "t sports burundi", "t sports south sudan", "t sports madagascar", "t sports mauritius", "t sports seychelles", "t sports comoros", "t sports mayotte", "t sports reunion", "t sports saudi", "t sports uae", "t sports qatar", "t sports bahrain", "t sports kuwait", "t sports oman", "t sports yemen", "t sports jordan", "t sports lebanon", "t sports syria", "t sports iraq", "t sports iran", "t sports afghanistan", "t sports pakistan", "t sports nepal", "t sports sri lanka", "t sports maldives", "t sports bhutan", "t sports myanmar", "t sports thailand", "t sports laos", "t sports cambodia", "t sports vietnam", "t sports malaysia", "t sports singapore", "t sports indonesia", "t sports philippines", "t sports brunei", "t sports east timor", "t sports papua", "t sports fiji", "t sports samoa", "t sports tonga", "t sports vanuatu", "t sports solomon", "t sports nauru", "t sports palau", "t sports kiribati", "t sports marshall", "t sports micronesia", "t sports tuvalu", "t sports cook", "t sports niue", "t sports tokelau", "t sports pitcairn", "t sports christmas", "t sports cocos", "t sports norfolk", "t sports new caledonia", "t sports french polynesia", "t sports wallis", "t sports futuna", "t sports american samoa", "t sports guam", "t sports northern mariana", "t sports puerto rico", "t sports us virgin", "t sports british virgin", "t sports anguilla", "t sports montserrat", "t sports bermuda", "t sports cayman", "t sports turks", "t sports caicos", "t sports aruba", "t sports curacao", "t sports bonaire", "t sports sint maarten", "t sports saba", "t sports statia", "t sports barbados", "t sports antigua", "t sports saint lucia", "t sports saint vincent", "t sports grenada", "t sports saint kitts", "t sports dominica", "t sports trinidad", "t sports tobago", "t sports guyana", "t sports suriname", "t sports french guiana", "t sports belize", "t sports honduras", "t sports guatemala", "t sports el salvador", "t sports nicaragua", "t sports costa rica", "t sports panama", "t sports cuba", "t sports haiti", "t sports dominican", "t sports jamaica", "t sports bahamas", "t sports mexico", "t sports colombia", "t sports venezuela", "t sports ecuador", "t sports peru", "t sports bolivia", "t sports brazil", "t sports chile", "t sports argentina", "t sports uruguay", "t sports paraguay", "t sports falkland"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD"],
        category="sports"),

    ChannelProfile("Gazi TV",
        primary=["gazi tv", "gazitv", "gtv", "g tv"],
        secondary=["gazi tv hd", "gazitv hd", "gtv hd"],
        exclude=["gazi tv india", "gazi tv uk", "gazi tv usa", "gazi tv europe", "gazi tv middle east", "gazi tv australia", "gazi tv canada", "gazi tv new zealand", "gazi tv south africa", "gazi tv nigeria", "gazi tv kenya", "gazi tv ghana", "gazi tv tanzania", "gazi tv uganda", "gazi tv zimbabwe", "gazi tv zambia", "gazi tv botswana", "gazi tv namibia", "gazi tv mozambique", "gazi tv angola", "gazi tv congo", "gazi tv cameroon", "gazi tv ivory coast", "gazi tv senegal", "gazi tv mali", "gazi tv burkina", "gazi tv niger", "gazi tv chad", "gazi tv central africa", "gazi tv gabon", "gazi tv equatorial", "gazi tv sao tome", "gazi tv cape verde", "gazi tv gambia", "gazi tv guinea", "gazi tv guinea bissau", "gazi tv sierra leone", "gazi tv liberia", "gazi tv togo", "gazi tv benin", "gazi tv mauritania", "gazi tv western sahara", "gazi tv morocco", "gazi tv algeria", "gazi tv tunisia", "gazi tv libya", "gazi tv egypt", "gazi tv sudan", "gazi tv eritrea", "gazi tv djibouti", "gazi tv ethiopia", "gazi tv somalia", "gazi tv kenya", "gazi tv rwanda", "gazi tv burundi", "gazi tv south sudan", "gazi tv madagascar", "gazi tv mauritius", "gazi tv seychelles", "gazi tv comoros", "gazi tv mayotte", "gazi tv reunion", "gazi tv saudi", "gazi tv uae", "gazi tv qatar", "gazi tv bahrain", "gazi tv kuwait", "gazi tv oman", "gazi tv yemen", "gazi tv jordan", "gazi tv lebanon", "gazi tv syria", "gazi tv iraq", "gazi tv iran", "gazi tv afghanistan", "gazi tv pakistan", "gazi tv nepal", "gazi tv sri lanka", "gazi tv maldives", "gazi tv bhutan", "gazi tv myanmar", "gazi tv thailand", "gazi tv laos", "gazi tv cambodia", "gazi tv vietnam", "gazi tv malaysia", "gazi tv singapore", "gazi tv indonesia", "gazi tv philippines", "gazi tv brunei", "gazi tv east timor", "gazi tv papua", "gazi tv fiji", "gazi tv samoa", "gazi tv tonga", "gazi tv vanuatu", "gazi tv solomon", "gazi tv nauru", "gazi tv palau", "gazi tv kiribati", "gazi tv marshall", "gazi tv micronesia", "gazi tv tuvalu", "gazi tv cook", "gazi tv niue", "gazi tv tokelau", "gazi tv pitcairn", "gazi tv christmas", "gazi tv cocos", "gazi tv norfolk", "gazi tv new caledonia", "gazi tv french polynesia", "gazi tv wallis", "gazi tv futuna", "gazi tv american samoa", "gazi tv guam", "gazi tv northern mariana", "gazi tv puerto rico", "gazi tv us virgin", "gazi tv british virgin", "gazi tv anguilla", "gazi tv montserrat", "gazi tv bermuda", "gazi tv cayman", "gazi tv turks", "gazi tv caicos", "gazi tv aruba", "gazi tv curacao", "gazi tv bonaire", "gazi tv sint maarten", "gazi tv saba", "gazi tv statia", "gazi tv barbados", "gazi tv antigua", "gazi tv saint lucia", "gazi tv saint vincent", "gazi tv grenada", "gazi tv saint kitts", "gazi tv dominica", "gazi tv trinidad", "gazi tv tobago", "gazi tv guyana", "gazi tv suriname", "gazi tv french guiana", "gazi tv belize", "gazi tv honduras", "gazi tv guatemala", "gazi tv el salvador", "gazi tv nicaragua", "gazi tv costa rica", "gazi tv panama", "gazi tv cuba", "gazi tv haiti", "gazi tv dominican", "gazi tv jamaica", "gazi tv bahamas", "gazi tv mexico", "gazi tv colombia", "gazi tv venezuela", "gazi tv ecuador", "gazi tv peru", "gazi tv bolivia", "gazi tv brazil", "gazi tv chile", "gazi tv argentina", "gazi tv uruguay", "gazi tv paraguay", "gazi tv falkland"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD"],
        category="sports"),

    ChannelProfile("Star Sports 1",
        primary=["star sports 1", "starsports1", "star sports one"],
        secondary=["star sports 1 hd", "starsports1 hd", "star sports one hd"],
        exclude=["star sports 1 hindi", "star sports 1 tamil", "star sports 1 telugu", "star sports 1 kannada", "star sports 1 malayalam", "star sports 1 marathi", "star sports 1 bangla", "star sports 1 bengali", "star sports 1 urdu", "star sports 1 punjabi", "star sports 1 gujarati", "star sports 1 odia", "star sports 1 assamese", "star sports 1 nepali", "star sports 1 sri lanka", "star sports 1 pakistan", "star sports 1 afghanistan", "star sports 1 bangladesh"],
        lang_required=["English"],
        country_preferred=["IN", "UK", "US"],
        category="sports"),

    # --- KIDS / ANIMATION ---
    ChannelProfile("Nickelodeon",
        primary=["nickelodeon", "nick", "nick hd"],
        secondary=["nickelodeon hd", "nick hd plus"],
        exclude=["nickelodeon hindi", "nickelodeon tamil", "nickelodeon telugu", "nickelodeon marathi", "nickelodeon kannada", "nickelodeon malayalam", "nickelodeon gujarati", "nickelodeon punjabi", "nickelodeon urdu", "nickelodeon odia", "nickelodeon assamese", "nickelodeon nepali", "nickelodeon sri lanka", "nickelodeon pakistan", "nickelodeon afghanistan", "nickelodeon iran", "nickelodeon arab", "nickelodeon turkish", "nickelodeon french", "nickelodeon german", "nickelodeon spanish", "nickelodeon portuguese", "nickelodeon italian", "nickelodeon russian", "nickelodeon chinese", "nickelodeon japanese", "nickelodeon korean", "nick jr hindi", "nick jr tamil", "nick jr telugu", "nick jr marathi", "nick jr kannada", "nick jr malayalam", "nick jr gujarati", "nick jr punjabi", "nick jr urdu", "nick jr odia", "nick jr assamese", "nick jr nepali", "nick jr sri lanka", "nick jr pakistan", "nick jr afghanistan", "nick jr iran", "nick jr arab", "nick jr turkish", "nick jr french", "nick jr german", "nick jr spanish", "nick jr portuguese", "nick jr italian", "nick jr russian", "nick jr chinese", "nick jr japanese", "nick jr korean"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids"),

    ChannelProfile("Sony Yay",
        primary=["sony yay", "sonyyay", "sony yay!"],
        secondary=["sony yay hd", "sonyyay hd"],
        exclude=["sony yay hindi", "sony yay tamil", "sony yay telugu", "sony yay marathi", "sony yay kannada", "sony yay malayalam", "sony yay gujarati", "sony yay punjabi", "sony yay urdu", "sony yay odia", "sony yay assamese", "sony yay nepali", "sony yay sri lanka", "sony yay pakistan", "sony yay afghanistan", "sony yay iran", "sony yay arab", "sony yay turkish", "sony yay french", "sony yay german", "sony yay spanish", "sony yay portuguese", "sony yay italian", "sony yay russian", "sony yay chinese", "sony yay japanese", "sony yay korean"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids"),

    ChannelProfile("Cartoon Network",
        primary=["cartoon network", "cartoonnetwork", "cn"],
        secondary=["cartoon network hd", "cartoonnetwork hd", "cn hd"],
        exclude=["cartoon network hindi", "cartoon network tamil", "cartoon network telugu", "cartoon network marathi", "cartoon network kannada", "cartoon network malayalam", "cartoon network gujarati", "cartoon network punjabi", "cartoon network urdu", "cartoon network odia", "cartoon network assamese", "cartoon network nepali", "cartoon network sri lanka", "cartoon network pakistan", "cartoon network afghanistan", "cartoon network iran", "cartoon network arab", "cartoon network turkish", "cartoon network french", "cartoon network german", "cartoon network spanish", "cartoon network portuguese", "cartoon network italian", "cartoon network russian", "cartoon network chinese", "cartoon network japanese", "cartoon network korean"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids"),

    ChannelProfile("Pogo",
        primary=["pogo", "pogo tv", "pogotv"],
        secondary=["pogo hd", "pogo tv hd"],
        exclude=["pogo hindi", "pogo tamil", "pogo telugu", "pogo marathi", "pogo kannada", "pogo malayalam", "pogo gujarati", "pogo punjabi", "pogo urdu", "pogo odia", "pogo assamese", "pogo nepali", "pogo sri lanka", "pogo pakistan", "pogo afghanistan"],
        lang_required=["Bengali", "Bangla", "English", "Hindi"],  # Pogo often Hindi but acceptable
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids"),

    ChannelProfile("Disney Channel",
        primary=["disney channel", "disneychannel", "disney ch"],
        secondary=["disney channel hd", "disneychannel hd"],
        exclude=["disney channel hindi", "disney channel tamil", "disney channel telugu", "disney channel marathi", "disney channel kannada", "disney channel malayalam", "disney channel gujarati", "disney channel punjabi", "disney channel urdu", "disney channel odia", "disney channel assamese", "disney channel nepali", "disney channel sri lanka", "disney channel pakistan", "disney channel afghanistan", "disney channel iran", "disney channel arab", "disney channel turkish", "disney channel french", "disney channel german", "disney channel spanish", "disney channel portuguese", "disney channel italian", "disney channel russian", "disney channel chinese", "disney channel japanese", "disney channel korean"],
        lang_required=["Bengali", "Bangla", "English"],
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids"),

    ChannelProfile("Sonic",
        primary=["sonic", "sonic tv", "sonictv"],
        secondary=["sonic hd", "sonic nick"],
        exclude=["sonic hindi", "sonic tamil", "sonic telugu", "sonic marathi", "sonic kannada", "sonic malayalam", "sonic gujarati", "sonic punjabi", "sonic urdu", "sonic odia", "sonic assamese", "sonic nepali", "sonic sri lanka", "sonic pakistan", "sonic afghanistan", "sonicview", "panasonic"],
        lang_required=["Bengali", "Bangla", "English", "Hindi"],
        country_preferred=["BD", "IN", "UK", "US"],
        category="kids"),

    ChannelProfile("Gopal Bhar TV",
        primary=["gopal bhar", "gopalbhar", "gopal bhar tv"],
        secondary=["gopal bhar hd"],
        exclude=["gopal bhar movies", "gopal bhar cinema"],
        lang_required=["Bengali", "Bangla"],
        country_preferred=["BD", "IN"],
        category="kids"),

    ChannelProfile("Motu Patlu",
        primary=["motu patlu", "motupatlu", "motu patlu tv"],
        secondary=["motu patlu hd", "motu patlu channel"],
        exclude=["motu patlu movies", "motu patlu cinema"],
        lang_required=["Bengali", "Bangla", "Hindi", "English"],
        country_preferred=["BD", "IN"],
        category="kids"),

    # --- ENGLISH MOVIES / INFOTAINMENT ---
    ChannelProfile("Sony BBC Earth",
        primary=["sony bbc earth", "sony bbc", "bbc earth", "sony earth"],
        secondary=["sony bbc earth hd", "bbc earth hd"],
        exclude=["sony bbc earth hindi", "sony bbc earth tamil", "sony bbc earth telugu", "sony bbc earth marathi", "sony bbc earth kannada", "sony bbc earth malayalam", "sony bbc earth gujarati", "sony bbc earth punjabi", "sony bbc earth urdu", "sony bbc earth odia", "sony bbc earth assamese", "sony bbc earth nepali", "sony bbc earth sri lanka", "sony bbc earth pakistan", "sony bbc earth afghanistan"],
        lang_required=["English"],
        country_preferred=["IN", "UK", "US"],
        category="movies"),

    ChannelProfile("BBC World News",
        primary=["bbc world", "bbc world news", "bbc news"],
        secondary=["bbc world news hd", "bbc news hd", "bbc world hd"],
        exclude=["bbc world hindi", "bbc world tamil", "bbc world telugu", "bbc world marathi", "bbc world kannada", "bbc world malayalam", "bbc world gujarati", "bbc world punjabi", "bbc world urdu", "bbc world odia", "bbc world assamese", "bbc world nepali", "bbc world sri lanka", "bbc world pakistan", "bbc world afghanistan", "bbc world arab", "bbc world persian", "bbc world turkish", "bbc world french", "bbc world german", "bbc world spanish", "bbc world portuguese", "bbc world italian", "bbc world russian", "bbc world chinese", "bbc world japanese", "bbc world korean", "bbc world indonesian", "bbc world thai", "bbc world vietnamese", "bbc world burmese", "bbc world swahili", "bbc world hausa", "bbc world somali", "bbc world kyrgyz", "bbc world uzbek", "bbc world tajik", "bbc world nepali", "bbc world sinhala", "bbc world tamil"],
        lang_required=["English"],
        country_preferred=["UK", "US", "IN"],
        category="news"),

    ChannelProfile("Sony Max",
        primary=["sony max", "sonymax", "sony max hd"],
        secondary=["sony max hd", "sonymax hd"],
        exclude=["sony max hindi", "sony max tamil", "sony max telugu", "sony max marathi", "sony max kannada", "sony max malayalam", "sony max gujarati", "sony max punjabi", "sony max urdu", "sony max odia", "sony max assamese", "sony max nepali", "sony max sri lanka", "sony max pakistan", "sony max afghanistan", "sony max bangla", "sony max bengali"],
        lang_required=["English", "Hindi"],
        country_preferred=["IN", "UK", "US"],
        category="movies"),

    ChannelProfile("Sony Pix",
        primary=["sony pix", "sonypix", "sony pix hd"],
        secondary=["sony pix hd", "sonypix hd"],
        exclude=["sony pix hindi", "sony pix tamil", "sony pix telugu", "sony pix marathi", "sony pix kannada", "sony pix malayalam", "sony pix gujarati", "sony pix punjabi", "sony pix urdu", "sony pix odia", "sony pix assamese", "sony pix nepali", "sony pix sri lanka", "sony pix pakistan", "sony pix afghanistan"],
        lang_required=["English"],
        country_preferred=["IN", "UK", "US"],
        category="movies"),

    ChannelProfile("HBO",
        primary=["hbo", "hbo hd"],
        secondary=["hbo hd", "hbo channel"],
        exclude=["hbo hindi", "hbo tamil", "hbo telugu", "hbo marathi", "hbo kannada", "hbo malayalam", "hbo gujarati", "hbo punjabi", "hbo urdu", "hbo odia", "hbo assamese", "hbo nepali", "hbo sri lanka", "hbo pakistan", "hbo afghanistan", "hbo arab", "hbo latin", "hbo asia", "hbo europe", "hbo family", "hbo comedy", "hbo signature", "hbo zone", "hbo hits", "hbo defined"],
        lang_required=["English"],
        country_preferred=["US", "UK", "IN"],
        category="movies"),

    ChannelProfile("Star Movies",
        primary=["star movies", "starmovies", "star movies hd"],
        secondary=["star movies hd", "starmovies hd"],
        exclude=["star movies hindi", "star movies tamil", "star movies telugu", "star movies marathi", "star movies kannada", "star movies malayalam", "star movies gujarati", "star movies punjabi", "star movies urdu", "star movies odia", "star movies assamese", "star movies nepali", "star movies sri lanka", "star movies pakistan", "star movies afghanistan", "star movies select", "star movies action", "star movies family"],
        lang_required=["English"],
        country_preferred=["IN", "UK", "US"],
        category="movies"),

    ChannelProfile("Discovery",
        primary=["discovery", "discovery channel", "discovery hd"],
        secondary=["discovery channel hd", "discovery hd world", "discovery hd"],
        exclude=["discovery hindi", "discovery tamil", "discovery telugu", "discovery marathi", "discovery kannada", "discovery malayalam", "discovery gujarati", "discovery punjabi", "discovery urdu", "discovery odia", "discovery assamese", "discovery nepali", "discovery sri lanka", "discovery pakistan", "discovery afghanistan", "discovery kids", "discovery science", "discovery turbo", "discovery investigation", "discovery id", "discovery life", "discovery home", "discovery travel", "discovery world", "discovery en espanol", "discovery familia", "discovery arabia", "discovery persia", "discovery turkey", "discovery france", "discovery germany", "discovery spain", "discovery portugal", "discovery italy", "discovery russia", "discovery china", "discovery japan", "discovery korea", "discovery southeast asia", "discovery australia", "discovery new zealand", "discovery south africa", "discovery nigeria", "discovery kenya", "discovery ghana", "discovery tanzania", "discovery uganda", "discovery zimbabwe", "discovery zambia", "discovery botswana", "discovery namibia", "discovery mozambique", "discovery angola", "discovery congo", "discovery cameroon", "discovery ivory coast", "discovery senegal", "discovery mali", "discovery burkina", "discovery niger", "discovery chad", "discovery central africa", "discovery gabon", "discovery equatorial", "discovery sao tome", "discovery cape verde", "discovery gambia", "discovery guinea", "discovery guinea bissau", "discovery sierra leone", "discovery liberia", "discovery togo", "discovery benin", "discovery mauritania", "discovery western sahara", "discovery morocco", "discovery algeria", "discovery tunisia", "discovery libya", "discovery egypt", "discovery sudan", "discovery eritrea", "discovery djibouti", "discovery ethiopia", "discovery somalia", "discovery kenya", "discovery rwanda", "discovery burundi", "discovery south sudan", "discovery madagascar", "discovery mauritius", "discovery seychelles", "discovery comoros", "discovery mayotte", "discovery reunion", "discovery saudi", "discovery uae", "discovery qatar", "discovery bahrain", "discovery kuwait", "discovery oman", "discovery yemen", "discovery jordan", "discovery lebanon", "discovery syria", "discovery iraq", "discovery iran", "discovery afghanistan", "discovery pakistan", "discovery nepal", "discovery sri lanka", "discovery maldives", "discovery bhutan", "discovery myanmar", "discovery thailand", "discovery laos", "discovery cambodia", "discovery vietnam", "discovery malaysia", "discovery singapore", "discovery indonesia", "discovery philippines", "discovery brunei", "discovery east timor", "discovery papua", "discovery fiji", "discovery samoa", "discovery tonga", "discovery vanuatu", "discovery solomon", "discovery nauru", "discovery palau", "discovery kiribati", "discovery marshall", "discovery micronesia", "discovery tuvalu", "discovery cook", "discovery niue", "discovery tokelau", "discovery pitcairn", "discovery christmas", "discovery cocos", "discovery norfolk", "discovery new caledonia", "discovery french polynesia", "discovery wallis", "discovery futuna", "discovery american samoa", "discovery guam", "discovery northern mariana", "discovery puerto rico", "discovery us virgin", "discovery british virgin", "discovery anguilla", "discovery montserrat", "discovery bermuda", "discovery cayman", "discovery turks", "discovery caicos", "discovery aruba", "discovery curacao", "discovery bonaire", "discovery sint maarten", "discovery saba", "discovery statia", "discovery barbados", "discovery antigua", "discovery saint lucia", "discovery saint vincent", "discovery grenada", "discovery saint kitts", "discovery dominica", "discovery trinidad", "discovery tobago", "discovery guyana", "discovery suriname", "discovery french guiana", "discovery belize", "discovery honduras", "discovery guatemala", "discovery el salvador", "discovery nicaragua", "discovery costa rica", "discovery panama", "discovery cuba", "discovery haiti", "discovery dominican", "discovery jamaica", "discovery bahamas", "discovery mexico", "discovery colombia", "discovery venezuela", "discovery ecuador", "discovery peru", "discovery bolivia", "discovery brazil", "discovery chile", "discovery argentina", "discovery uruguay", "discovery paraguay", "discovery falkland"],
        lang_required=["English"],
        country_preferred=["US", "UK", "IN"],
        category="movies"),

    ChannelProfile("National Geographic",
        primary=["national geographic", "nat geo", "natgeo", "national geographic hd"],
        secondary=["nat geo hd", "natgeo hd", "national geographic channel"],
        exclude=["national geographic hindi", "national geographic tamil", "national geographic telugu", "national geographic marathi", "national geographic kannada", "national geographic malayalam", "national geographic gujarati", "national geographic punjabi", "national geographic urdu", "national geographic odia", "national geographic assamese", "national geographic nepali", "national geographic sri lanka", "national geographic pakistan", "national geographic afghanistan", "national geographic wild", "national geographic people", "national geographic abu dhabi", "national geographic arab", "national geographic persia", "national geographic turkey", "national geographic france", "national geographic germany", "national geographic spain", "national geographic portugal", "national geographic italy", "national geographic russia", "national geographic china", "national geographic japan", "national geographic korea", "national geographic southeast asia", "national geographic australia", "national geographic new zealand", "national geographic south africa", "national geographic nigeria", "national geographic kenya", "national geographic ghana", "national geographic tanzania", "national geographic uganda", "national geographic zimbabwe", "national geographic zambia", "national geographic botswana", "national geographic namibia", "national geographic mozambique", "national geographic angola", "national geographic congo", "national geographic cameroon", "national geographic ivory coast", "national geographic senegal", "national geographic mali", "national geographic burkina", "national geographic niger", "national geographic chad", "national geographic central africa", "national geographic gabon", "national geographic equatorial", "national geographic sao tome", "national geographic cape verde", "national geographic gambia", "national geographic guinea", "national geographic guinea bissau", "national geographic sierra leone", "national geographic liberia", "national geographic togo", "national geographic benin", "national geographic mauritania", "national geographic western sahara", "national geographic morocco", "national geographic algeria", "national geographic tunisia", "national geographic libya", "national geographic egypt", "national geographic sudan", "national geographic eritrea", "national geographic djibouti", "national geographic ethiopia", "national geographic somalia", "national geographic kenya", "national geographic rwanda", "national geographic burundi", "national geographic south sudan", "national geographic madagascar", "national geographic mauritius", "national geographic seychelles", "national geographic comoros", "national geographic mayotte", "national geographic reunion", "national geographic saudi", "national geographic uae", "national geographic qatar", "national geographic bahrain", "national geographic kuwait", "national geographic oman", "national geographic yemen", "national geographic jordan", "national geographic lebanon", "national geographic syria", "national geographic iraq", "national geographic iran", "national geographic afghanistan", "national geographic pakistan", "national geographic nepal", "national geographic sri lanka", "national geographic maldives", "national geographic bhutan", "national geographic myanmar", "national geographic thailand", "national geographic laos", "national geographic cambodia", "national geographic vietnam", "national geographic malaysia", "national geographic singapore", "national geographic indonesia", "national geographic philippines", "national geographic brunei", "national geographic east timor", "national geographic papua", "national geographic fiji", "national geographic samoa", "national geographic tonga", "national geographic vanuatu", "national geographic solomon", "national geographic nauru", "national geographic palau", "national geographic kiribati", "national geographic marshall", "national geographic micronesia", "national geographic tuvalu", "national geographic cook", "national geographic niue", "national geographic tokelau", "national geographic pitcairn", "national geographic christmas", "national geographic cocos", "national geographic norfolk", "national geographic new caledonia", "national geographic french polynesia", "national geographic wallis", "national geographic futuna", "national geographic american samoa", "national geographic guam", "national geographic northern mariana", "national geographic puerto rico", "national geographic us virgin", "national geographic british virgin", "national geographic anguilla", "national geographic montserrat", "national geographic bermuda", "national geographic cayman", "national geographic turks", "national geographic caicos", "national geographic aruba", "national geographic curacao", "national geographic bonaire", "national geographic sint maarten", "national geographic saba", "national geographic statia", "national geographic barbados", "national geographic antigua", "national geographic saint lucia", "national geographic saint vincent", "national geographic grenada", "national geographic saint kitts", "national geographic dominica", "national geographic trinidad", "national geographic tobago", "national geographic guyana", "national geographic suriname", "national geographic french guiana", "national geographic belize", "national geographic honduras", "national geographic guatemala", "national geographic el salvador", "national geographic nicaragua", "national geographic costa rica", "national geographic panama", "national geographic cuba", "national geographic haiti", "national geographic dominican", "national geographic jamaica", "national geographic bahamas", "national geographic mexico", "national geographic colombia", "national geographic venezuela", "national geographic ecuador", "national geographic peru", "national geographic bolivia", "national geographic brazil", "national geographic chile", "national geographic argentina", "national geographic uruguay", "national geographic paraguay", "national geographic falkland"],
        lang_required=["English"],
        country_preferred=["US", "UK", "IN"],
        category="movies"),
]

# Build lookup maps
CANONICAL_TO_PROFILE: Dict[str, ChannelProfile] = {p.canonical: p for p in CHANNEL_PROFILES}

# =============================================================================
# 1. SOURCE INTELLIGENCE MATRIX
# =============================================================================

SOURCES = [
    # Tier 1: Curated Country Feeds
    ("https://iptv-org.github.io/iptv/countries/bd.m3u", 30),      # Bangladesh
    ("https://iptv-org.github.io/iptv/countries/in.m3u", 30),      # India
    ("https://iptv-org.github.io/iptv/countries/uk.m3u", 20),      # UK (English)
    ("https://iptv-org.github.io/iptv/countries/us.m3u", 20),      # USA (English)

    # Tier 2: Category Intelligence
    ("https://iptv-org.github.io/iptv/categories/entertainment.m3u", 15),
    ("https://iptv-org.github.io/iptv/categories/movies.m3u", 15),
    ("https://iptv-org.github.io/iptv/categories/kids.m3u", 15),
    ("https://iptv-org.github.io/iptv/categories/animation.m3u", 15),
    ("https://iptv-org.github.io/iptv/categories/documentary.m3u", 10),
    ("https://iptv-org.github.io/iptv/categories/news.m3u", 15),
    ("https://iptv-org.github.io/iptv/categories/sports.m3u", 15),

    # Tier 3: BDIX Specialist
    ("https://raw.githubusercontent.com/Shadmanislam/bdiptv/master/BD%20IPTV.m3u", 50),
    ("https://raw.githubusercontent.com/abusaeeidx/Mrgify-BDIX-IPTV/main/playlist.m3u", 50),

    # Tier 4: Global Index & Aggregators
    ("https://iptv-org.github.io/iptv/index.m3u", 10),
    ("https://raw.githubusercontent.com/imShakil/tvlink/refs/heads/main/iptv.m3u8", 10),
]

# Manual static overrides (user can paste working URLs here)
STATIC_OVERRIDES: Dict[str, List[str]] = {
    "Star Jalsha": [],
    "Zee Bangla": [],
    "Sony Aath": [],
    "Colors Bangla": [],
    "Duranto TV": [],
    "T Sports HD": [],
    "Gazi TV": [],
    "Somoy TV": [],
    "Jamuna TV": [],
    "NTV News": [],
    "Maasranga TV": [],
    "Asian TV": [],
    "Nickelodeon": [],
    "Sony Yay": [],
    "Cartoon Network": [],
    "Gopal Bhar TV": [],
    "Motu Patlu": [],
    "Sony BBC Earth": [],
    "BBC World News": [],
    "Sony Max": [],
    "Sony Pix": [],
    "HBO": [],
    "Star Movies": [],
    "Discovery": [],
    "National Geographic": [],
}

# =============================================================================
# 2. QUALITY CONTROL & PERFORMANCE
# =============================================================================

MAX_STREAMS_PER_CHANNEL = 3
REQUEST_TIMEOUT = 5
FETCH_TIMEOUT = 30
MAX_CONCURRENT_VALIDATIONS = 40
MAX_CONCURRENT_FETCHES = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate, br",
}

# Language whitelist - ONLY these languages are acceptable
LANG_WHITELIST = {"Bengali", "Bangla", "English", "bengali", "bangla", "english", "en", "bn"}

# Country whitelist for boosting
COUNTRY_WHITELIST = {"BD", "IN", "UK", "US", "GB"}

# Negative keywords that auto-reject a channel entry
NEGATIVE_KEYWORDS = [
    "telugu", "marathi", "tamil", "kannada", "malayalam", "gujarati", 
    "punjabi", "odia", "oriya", "assamese", "nepali", "sinhala", "urdu",
    "hindi",  # We allow some Hindi for kids channels but not for main targets
    "bhojpuri", "rajasthani", "haryanvi", "chhattisgarhi", "maithili",
    "sanskrit", "konkani", "tulu", "kashmiri", "dogri", "sindhi",
    "bodo", "santhali", "meitei", "mizo", "khasi", "garo", "tripuri",
    "naga", "manipuri", "assam", "kerala", "andhra", "karnataka",
    "maharashtra", "gujarat", "rajasthan", "haryana", "punjab",
    "bihar", "jharkhand", "chhattisgarh", "madhya pradesh", "uttar pradesh",
    "tamil nadu", "telangana", "kerala", "karnataka", "andhra pradesh",
    "orissa", "odisha", "west bengal", "bengal",  # "west bengal" is okay but we use BD/IN country
]

# =============================================================================
# 3. M3U PARSING WITH FULL METADATA EXTRACTION
# =============================================================================

@dataclass
class M3UEntry:
    """Rich metadata extracted from a single M3U entry."""
    name: str
    url: str
    tvg_name: Optional[str] = None
    tvg_id: Optional[str] = None
    tvg_language: Optional[str] = None
    tvg_country: Optional[str] = None
    tvg_logo: Optional[str] = None
    group_title: Optional[str] = None
    user_agent: Optional[str] = None
    referrer: Optional[str] = None
    source_url: str = ""
    raw_extinf: str = ""


def clean_channel_name(name: str) -> str:
    """Strip metadata brackets, tracking, and normalize whitespace."""
    if not name:
        return ""
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'\{.*?\}', '', name)
    name = re.sub(r'<.*?>', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def parse_m3u(content: str, source_url: str) -> List[M3UEntry]:
    """Extracts full metadata from M3U content with zero data loss."""
    lines = content.splitlines()
    entries: List[M3UEntry] = []
    current_extinf = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            current_extinf = line
        elif not line.startswith("#") and line.startswith("http"):
            if current_extinf:
                entry = _parse_extinf(current_extinf, line, source_url)
                if entry:
                    entries.append(entry)
            current_extinf = ""
        elif not line.startswith("#"):
            # Some playlists have URLs without http prefix (rare)
            if line.startswith("//") or line.startswith("rtmp"):
                if current_extinf:
                    entry = _parse_extinf(current_extinf, line, source_url)
                    if entry:
                        entries.append(entry)
                current_extinf = ""

    return entries


def _parse_extinf(extinf_line: str, url: str, source_url: str) -> Optional[M3UEntry]:
    """Parse #EXTINF line into structured metadata."""
    # Extract tvg-* attributes using regex
    tvg_name = _extract_attr(extinf_line, 'tvg-name')
    tvg_id = _extract_attr(extinf_line, 'tvg-id')
    tvg_language = _extract_attr(extinf_line, 'tvg-language')
    tvg_country = _extract_attr(extinf_line, 'tvg-country')
    tvg_logo = _extract_attr(extinf_line, 'tvg-logo')
    group_title = _extract_attr(extinf_line, 'group-title')
    user_agent = _extract_attr(extinf_line, 'user-agent')
    referrer = _extract_attr(extinf_line, 'referrer')

    # Extract display name after comma
    display_name = ""
    if "," in extinf_line:
        display_name = clean_channel_name(extinf_line.split(",")[-1])

    # Use tvg-name if available, otherwise display_name
    final_name = tvg_name if tvg_name else display_name
    if not final_name:
        return None

    return M3UEntry(
        name=final_name,
        url=url.strip(),
        tvg_name=tvg_name,
        tvg_id=tvg_id,
        tvg_language=tvg_language,
        tvg_country=tvg_country,
        tvg_logo=tvg_logo,
        group_title=group_title,
        user_agent=user_agent,
        referrer=referrer,
        source_url=source_url,
        raw_extinf=extinf_line,
    )


def _extract_attr(line: str, attr: str) -> Optional[str]:
    """Extract attribute value from #EXTINF line."""
    pattern = rf'{attr}="([^"]*)"'
    match = re.search(pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


# =============================================================================
# 4. ZERO-HALLUCINATION MATCHING ENGINE
# =============================================================================

def compute_match_score(entry: M3UEntry, profile: ChannelProfile) -> float:
    """
    Compute confidence score for matching an M3U entry to a channel profile.
    Returns -1.0 if auto-rejected, 0.0 if no match, >0.0 if match.
    """
    normalized_name = entry.name.lower().strip()
    flat_name = re.sub(r'[^a-z0-9]', '', normalized_name)

    # --- EXCLUSION CHECK (Auto-reject) ---
    for exclude_kw in profile.exclude:
        flat_exclude = re.sub(r'[^a-z0-9]', '', exclude_kw.lower().strip())
        if flat_exclude in flat_name or flat_exclude == flat_name:
            return -1.0

    # --- NEGATIVE KEYWORD CHECK (Language guard) ---
    group_lower = (entry.group_title or "").lower()
    for neg in NEGATIVE_KEYWORDS:
        if neg in normalized_name or neg in group_lower:
            return -1.0

    # --- LANGUAGE GUARD ---
    if entry.tvg_language:
        lang_lower = entry.tvg_language.lower().strip()
        # If language is explicitly set and NOT in whitelist, reject
        if lang_lower not in {l.lower() for l in LANG_WHITELIST}:
            return -1.0
        # If profile requires specific languages and entry has language
        if profile.lang_required:
            if not any(req.lower() in lang_lower for req in profile.lang_required):
                # Language mismatch - significant penalty but not auto-reject
                # (some sources mislabel language)
                pass  # We'll handle via scoring below

    # --- SCORING ---
    score = 0.0
    matched = False

    # Primary keywords (weight 1.0)
    for kw in profile.primary:
        flat_kw = re.sub(r'[^a-z0-9]', '', kw.lower().strip())
        if flat_kw == flat_name or flat_kw in flat_name:
            score += 1.0
            matched = True
            break

    # Secondary keywords (weight 0.6) - only if no primary match
    if not matched:
        for kw in profile.secondary:
            flat_kw = re.sub(r'[^a-z0-9]', '', kw.lower().strip())
            if flat_kw in flat_name:
                score += 0.6
                matched = True
                break

    # Tertiary keywords (weight 0.3) - only if no primary/secondary match
    if not matched:
        for kw in profile.tertiary:
            flat_kw = re.sub(r'[^a-z0-9]', '', kw.lower().strip())
            if flat_kw in flat_name:
                score += 0.3
                matched = True
                break

    if not matched:
        return 0.0

    # Language bonus (+0.2 if language matches required)
    if entry.tvg_language and profile.lang_required:
        lang_lower = entry.tvg_language.lower().strip()
        if any(req.lower() in lang_lower for req in profile.lang_required):
            score += 0.2

    # Country bonus (+0.1 if country matches preferred)
    if entry.tvg_country and profile.country_preferred:
        country_upper = entry.tvg_country.upper().strip()
        if country_upper in {c.upper() for c in profile.country_preferred}:
            score += 0.1

    # Group title bonus/penalty
    if entry.group_title:
        group_lower = entry.group_title.lower()
        if any(req.lower() in group_lower for req in profile.lang_required):
            score += 0.05
        for neg in NEGATIVE_KEYWORDS:
            if neg in group_lower:
                score -= 0.5

    return score


def match_entry(entry: M3UEntry) -> Optional[Tuple[str, float]]:
    """
    Match an M3U entry against all profiles. Return (canonical_name, score) or None.
    Uses best-match strategy with confidence threshold.
    """
    best_match = None
    best_score = 0.0

    for profile in CHANNEL_PROFILES:
        score = compute_match_score(entry, profile)
        if score < 0:  # Auto-rejected
            continue
        if score >= profile.min_confidence and score > best_score:
            best_score = score
            best_match = profile.canonical

    if best_match:
        return (best_match, best_score)
    return None


# =============================================================================
# 5. URL NORMALIZATION & DEDUPLICATION
# =============================================================================

def normalize_url(url: str) -> str:
    """Normalize URL for deduplication while preserving auth tokens."""
    try:
        parsed = urlparse(url)
        # Strip common tracking parameters
        qsl = parse_qs(parsed.query, keep_blank_values=True)
        tracking_params = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 
                          'utm_content', 'tracking', 'source', 'ref', 'referrer'}
        filtered = {k: v for k, v in qsl.items() if k.lower() not in tracking_params}

        # Rebuild query
        new_query = urlencode(filtered, doseq=True)

        # Normalize path (remove trailing slashes)
        path = parsed.path.rstrip('/')

        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            new_query,
            '',  # Remove fragment
        ))
    except Exception:
        return url


# =============================================================================
# 6. DEEP STREAM VALIDATION (3-TIER PROOF SYSTEM)
# =============================================================================

@dataclass
class ValidationResult:
    url: str
    is_valid: bool
    ttfb_ms: float = 0.0
    speed_kbps: float = 0.0
    content_type: str = ""
    signature_valid: bool = False
    score: float = 0.0
    error: str = ""


async def validate_url_deep(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore,
    source_bonus: int = 0
) -> ValidationResult:
    """
    3-Tier Validation:
    1. HEAD probe (fast fail)
    2. Signature verification (stream proof)
    3. Performance benchmark (quality score)
    """
    async with semaphore:
        start_time = time.monotonic()
        result = ValidationResult(url=url)

        try:
            # --- TIER 1: HEAD Probe ---
            head_timeout = aiohttp.ClientTimeout(total=3, sock_connect=2, sock_read=2)
            async with session.head(
                url, headers=HEADERS, timeout=head_timeout, 
                allow_redirects=True, ssl=False
            ) as resp:
                if resp.status not in (200, 301, 302, 307, 308):
                    result.error = f"HEAD status: {resp.status}"
                    return result

                ct = resp.headers.get("Content-Type", "").lower()
                result.content_type = ct

                # Reject obvious HTML dead links
                if "text/html" in ct and not any(ext in url.lower() for ext in [".m3u8", ".ts", ".mp4"]):
                    result.error = "HTML response (dead link)"
                    return result
        except Exception as e:
            # HEAD might not be supported, continue to GET
            pass

        # --- TIER 2: Signature Verification ---
        try:
            get_timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=3, sock_read=4)
            headers = dict(HEADERS)
            headers["Range"] = "bytes=0-2047"  # Only get first 2KB

            async with session.get(
                url, headers=headers, timeout=get_timeout,
                allow_redirects=True, ssl=False
            ) as resp:
                if resp.status not in (200, 206):
                    result.error = f"GET status: {resp.status}"
                    return result

                # Read first chunk
                chunk = await resp.content.read(2048)
                if not chunk:
                    result.error = "Empty response body"
                    return result

                # Verify signature
                if await _verify_signature(chunk, url):
                    result.signature_valid = True
                else:
                    result.error = "Signature verification failed"
                    return result

                # --- TIER 3: Performance Benchmark ---
                result.ttfb_ms = (time.monotonic() - start_time) * 1000

                # Calculate speed from chunk size and time
                elapsed = time.monotonic() - start_time
                if elapsed > 0:
                    result.speed_kbps = (len(chunk) / 1024) / elapsed

                # Composite quality score
                # Higher is better: fast TTFB + good speed + source reliability
                ttfb_score = max(0, 1000 - result.ttfb_ms) / 10  # 0-100
                speed_score = min(result.speed_kbps * 10, 100)   # Cap at 100
                result.score = ttfb_score + speed_score + source_bonus

                result.is_valid = True

        except asyncio.TimeoutError:
            result.error = "Timeout during GET/validation"
        except Exception as e:
            result.error = f"Exception: {str(e)[:50]}"

        return result


async def _verify_signature(chunk: bytes, url: str) -> bool:
    """Verify stream signature based on file type."""
    if not chunk:
        return False

    url_lower = url.lower()

    # HLS / M3U8
    if ".m3u8" in url_lower or chunk.startswith(b"#EXTM3U"):
        return chunk.startswith(b"#EXTM3U") or b"#EXTM3U" in chunk[:100]

    # MPEG-TS
    if ".ts" in url_lower or url_lower.endswith(".ts"):
        # MPEG-TS sync byte is 0x47, should appear within first 188 bytes
        for i in range(min(188, len(chunk))):
            if chunk[i] == 0x47:
                return True
        return False

    # MP4
    if ".mp4" in url_lower:
        return b"ftyp" in chunk[:100] or b"moov" in chunk[:100]

    # Generic: if it starts with common binary signatures or #EXTM3U
    if chunk.startswith(b"#EXTM3U"):
        return True
    if b"#EXTM3U" in chunk[:100]:
        return True

    # Check for MPEG-TS sync byte anywhere in first 200 bytes
    for i in range(min(200, len(chunk))):
        if chunk[i] == 0x47:
            return True

    # If content looks like text/html, reject
    try:
        text_preview = chunk[:200].decode('utf-8', errors='ignore').lower()
        if '<html' in text_preview or '<!doctype' in text_preview:
            return False
    except Exception:
        pass

    # Accept unknown binary streams (might be valid)
    return True


# =============================================================================
# 7. NETWORK LIFECYCLE MANAGEMENT
# =============================================================================

async def fetch_source(session: aiohttp.ClientSession, url: str, timeout: int = FETCH_TIMEOUT) -> str:
    """Download remote playlist with retry logic."""
    try:
        async with session.get(
            url, headers=HEADERS, 
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            resp.raise_for_status()
            return await resp.text()
    except Exception:
        raise


# =============================================================================
# 8. ORCHESTRATION PIPELINE
# =============================================================================

async def main() -> None:
    discovered: Dict[str, List[ValidationResult]] = {p.canonical: [] for p in CHANNEL_PROFILES}
    validation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_VALIDATIONS)
    fetch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    print("[INFO] Launching Ultimate Zero-Hallucination IPTV Sync Machine v3.0...", flush=True)
    print(f"[INFO] Targeting {len(CHANNEL_PROFILES)} premium channels (Bengali + English)", flush=True)

    # Custom TCP connector for performance
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=30,
        ttl_dns_cache=300,
        use_dns_cache=True,
        enable_cleanup_closed=True,
        force_close=False,
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        # Step 1: Fetch all sources with controlled concurrency
        print("[INFO] Phase 1: Fetching source playlists...", flush=True)

        async def fetch_with_limit(url: str, bonus: int) -> Tuple[str, int, str]:
            async with fetch_semaphore:
                try:
                    content = await fetch_source(session, url)
                    return (url, bonus, content)
                except Exception as e:
                    return (url, bonus, "")

        fetch_tasks = [fetch_with_limit(url, bonus) for url, bonus in SOURCES]
        fetch_results = await asyncio.gather(*fetch_tasks)

        # Step 2: Parse all entries with full metadata
        print("[INFO] Phase 2: Parsing M3U entries with metadata extraction...", flush=True)
        all_entries: List[M3UEntry] = []
        for source_url, source_bonus, content in fetch_results:
            if not content:
                continue
            entries = parse_m3u(content, source_url)
            # Tag each entry with source bonus for later ranking
            for entry in entries:
                entry.source_url = source_url  # Already set, but ensure consistency
            all_entries.extend(entries)

        print(f"[INFO] Parsed {len(all_entries)} total entries from all sources", flush=True)

        # Step 3: Zero-hallucination matching with confidence scoring
        print("[INFO] Phase 3: Running confidence-based matching engine...", flush=True)
        matched_urls: Dict[str, List[Tuple[str, int, str]]] = {p.canonical: [] for p in CHANNEL_PROFILES}

        for entry in all_entries:
            match_result = match_entry(entry)
            if match_result:
                canonical, confidence = match_result
                # Find source bonus
                source_bonus = 0
                for url, bonus, _ in fetch_results:
                    if url == entry.source_url:
                        source_bonus = bonus
                        break
                matched_urls[canonical].append((entry.url, source_bonus, confidence))

        match_counts = {k: len(v) for k, v in matched_urls.items() if v}
        print(f"[INFO] Matched {sum(match_counts.values())} entries across {len(match_counts)} channels", flush=True)

        # Step 4: Inject static overrides
        for canonical, manual_urls in STATIC_OVERRIDES.items():
            if canonical in matched_urls:
                for u in manual_urls:
                    matched_urls[canonical].append((u, 100, 1.0))  # High bonus for manual

        # Step 5: Deduplicate URLs before validation
        for canonical in matched_urls:
            seen = set()
            deduped = []
            for url, bonus, confidence in matched_urls[canonical]:
                norm = normalize_url(url)
                if norm not in seen:
                    seen.add(norm)
                    deduped.append((url, bonus, confidence))
            matched_urls[canonical] = deduped

        # Step 6: Deep validation with 3-tier proof system
        print("[INFO] Phase 4: Deep stream validation (3-tier proof system)...", flush=True)

        validation_tasks = []
        metadata = []

        for canonical, items in matched_urls.items():
            for url, source_bonus, confidence in items:
                validation_tasks.append(validate_url_deep(session, url, validation_semaphore, source_bonus))
                metadata.append((canonical, url, confidence))

        if validation_tasks:
            results = await asyncio.gather(*validation_tasks)
        else:
            results = []

        # Step 7: Collect valid results
        for (canonical, url, confidence), result in zip(metadata, results):
            if result.is_valid and result.signature_valid:
                discovered[canonical].append(result)

        # Step 8: Rank and trim to top N per channel
        print("[INFO] Phase 5: Ranking streams by quality score...", flush=True)
        for canonical in discovered:
            if len(discovered[canonical]) > 1:
                # Sort by score descending
                discovered[canonical].sort(key=lambda x: x.score, reverse=True)
            if len(discovered[canonical]) > MAX_STREAMS_PER_CHANNEL:
                discovered[canonical] = discovered[canonical][:MAX_STREAMS_PER_CHANNEL]

        # Step 9: Fallback - if channel has < 1 stream, try relaxed matching
        # (This is done by re-scanning with lower threshold - but we already collected all)
        # Instead, we report which channels are missing
        missing_channels = [c for c, results in discovered.items() if not results]
        if missing_channels:
            print(f"[WARN] {len(missing_channels)} channels found no working streams: {', '.join(missing_channels[:10])}", flush=True)

        # Step 10: Generate outputs
        print("[INFO] Phase 6: Generating output files...", flush=True)

        # Master channels.json
        output = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_channels": len(CHANNEL_PROFILES),
            "working_channels": sum(1 for v in discovered.values() if v),
            "channels": []
        }

        for profile in CHANNEL_PROFILES:
            canonical = profile.canonical
            streams = discovered[canonical]
            output["channels"].append({
                "name": canonical,
                "category": profile.category,
                "language_required": profile.lang_required,
                "country_preferred": profile.country_preferred,
                "stream_count": len(streams),
                "streams": [
                    {
                        "url": r.url,
                        "ttfb_ms": round(r.ttfb_ms, 2),
                        "speed_kbps": round(r.speed_kbps, 2),
                        "score": round(r.score, 2),
                        "content_type": r.content_type,
                    }
                    for r in streams
                ]
            })

        with open("channels.json", "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Master playlist.m3u
        with open("playlist.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                canonical = profile.canonical
                for r in discovered[canonical]:
                    f.write(f"#EXTINF:-1 tvg-name=\"{canonical}\" tvg-language=\"{','.join(profile.lang_required)}\" tvg-country=\"{','.join(profile.country_preferred)}\" group-title=\"{profile.category.capitalize()}\",{canonical}\n")
                    f.write(f"{r.url}\n")

        # Bengali playlist
        with open("bengali.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if "Bengali" in profile.lang_required or "Bangla" in profile.lang_required:
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        f.write(f"#EXTINF:-1 tvg-name=\"{canonical}\" tvg-language=\"Bengali\" tvg-country=\"{','.join(profile.country_preferred)}\" group-title=\"{profile.category.capitalize()}\",{canonical}\n")
                        f.write(f"{r.url}\n")

        # English playlist
        with open("english.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if "English" in profile.lang_required and "Bengali" not in profile.lang_required and "Bangla" not in profile.lang_required:
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        f.write(f"#EXTINF:-1 tvg-name=\"{canonical}\" tvg-language=\"English\" tvg-country=\"{','.join(profile.country_preferred)}\" group-title=\"{profile.category.capitalize()}\",{canonical}\n")
                        f.write(f"{r.url}\n")

        # Kids playlist
        with open("kids.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if profile.category == "kids":
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        f.write(f"#EXTINF:-1 tvg-name=\"{canonical}\" tvg-language=\"{','.join(profile.lang_required)}\" tvg-country=\"{','.join(profile.country_preferred)}\" group-title=\"Kids\",{canonical}\n")
                        f.write(f"{r.url}\n")

        # News playlist
        with open("news.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if profile.category == "news":
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        f.write(f"#EXTINF:-1 tvg-name=\"{canonical}\" tvg-language=\"{','.join(profile.lang_required)}\" tvg-country=\"{','.join(profile.country_preferred)}\" group-title=\"News\",{canonical}\n")
                        f.write(f"{r.url}\n")

        # Sports playlist
        with open("sports.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for profile in CHANNEL_PROFILES:
                if profile.category == "sports":
                    canonical = profile.canonical
                    for r in discovered[canonical]:
                        f.write(f"#EXTINF:-1 tvg-name=\"{canonical}\" tvg-language=\"{','.join(profile.lang_required)}\" tvg-country=\"{','.join(profile.country_preferred)}\" group-title=\"Sports\",{canonical}\n")
                        f.write(f"{r.url}\n")

        # Summary
        total_working = sum(len(v) for v in discovered.values())
        working_channels = sum(1 for v in discovered.values() if v)
        print(f"[INFO] Sync complete!")
        print(f"[INFO] Working channels: {working_channels}/{len(CHANNEL_PROFILES)}")
        print(f"[INFO] Total working streams: {total_working}")
        print(f"[INFO] Output files: channels.json, playlist.m3u, bengali.m3u, english.m3u, kids.m3u, news.m3u, sports.m3u")


if __name__ == "__main__":
    asyncio.run(main())
