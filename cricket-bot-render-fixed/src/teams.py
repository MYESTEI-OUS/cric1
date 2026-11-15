"""Bundled international and IPL franchise starter squads; player lists are not live team sheets."""

import zlib

TEAMS = {
    "india": {
        "name": "India",
        "league": "international",
        "logo": "🇮🇳",
        "players": [
            "Shreyas Iyer", "Tilak Varma", "Abhishek Sharma", "Vaibhav Sooryavanshi",
"Ishan Kishan", "Sanju Samson", "Rinku Singh", "Shivam Dube",
"Axar Patel", "Washington Sundar", "Nitish Kumar Reddy", "Kuldeep Yadav",
"Ravi Bishnoi", "Arshdeep Singh", "Prince Yadav", "Mayank Yadav",

        ],
    },
    "australia": {
        "name": "Australia",
        "league": "international",
        "logo": "🌏",
        "players": [
            "Mitchell Marsh", "Xavier Bartlett", "Mahli Beardman", "Nikhil Chaudhary",
"Tim David", "Joel Davies", "Jack Edwards", "Nathan Ellis",
"Jake Fraser-McGurk", "Sam Harper", "Spencer Johnson", "Mitchell Owen",
"Lachlan Shaw", "Adam Zampa",

        ],
    },
    "england": {
        "name": "England",
        "league": "international",
        "logo": "🌏",
        "players": [
            "Harry Brook", "Tom Banton", "James Coles", "Jordan Cox",
"Henry Crocombe", "Sam Curran", "Liam Dawson", "Aneurin Donald",
"Eddie Jack", "Will Jacks", "Jamie Overton", "Adil Rashid",
"Thomas Rew", "Phil Salt", "Luke Wood",

        ],
    },
    "pakistan": {
        "name": "Pakistan",
        "league": "international",
        "logo": "🌏",
        "players": [
            "Sahibzada Farhan", "Abdul Samad", "Fakhar Zaman", "Hasan Nawaz",
"Khawaja Nafay", "Arafat Minhas", "Maaz Sadaqat", "Mohammad Imran",
"Saim Ayub", "Shadab Khan", "Abrar Ahmed", "Naseem Shah",
"Razaullah", "Salman Mirza", "Sufyan Moqim",
        ],
    },
    "new_zealand": {
        "name": "New Zealand",
        "league": "international",
        "logo": "🌏",
        "players": [
            "Mitchell Santner", "Finn Allen", "Mark Chapman", "Devon Conway",
"Jacob Duffy", "Lockie Ferguson", "Matt Henry", "Kyle Jamieson",
"Cole McConchie", "Daryl Mitchell", "James Neesham", "Glenn Phillips",
"Rachin Ravindra", "Tim Seifert", "Ish Sodhi",
        ],
    },
    "south_africa": {
        "name": "South Africa",
        "league": "international",
        "logo": "🌏",
        "players": [
            "Aiden Markram", "Corbin Bosch", "Dewald Brevis", "Quinton de Kock",
"Marco Jansen", "George Linde", "Keshav Maharaj", "Kwena Maphaka",
"David Miller", "Lungi Ngidi", "Anrich Nortje", "Kagiso Rabada",
"Ryan Rickelton", "Jason Smith", "Tristan Stubbs",
        ],
    },
    "sri_lanka": {
        "name": "Sri Lanka",
        "league": "international",
        "logo": "🌏",
        "players": [
            "Kusal Mendis", "Kamil Mishara", "Sineth Jayawardena", "Lahiru Udara",
"Sahan Arachchige", "Kamindu Mendis", "Dasun Shanaka", "Chamindu Wickramasinghe",
"Dushmantha Chameera", "Binura Fernando", "Eshan Malinga", "Maheesh Theekshana",
"Nuwan Thushara", "Vijayakanth Viyaskanth", "Dunith Wellalage",
        ],
    },
    "west_indies": {
        "name": "West Indies",
        "league": "international",
        "logo": "🌏",
        "players": [
            "Nicholas Pooran", "Shai Hope", "Andre Russell", "Jason Holder",
            "Rovman Powell", "Shimron Hetmyer", "Alzarri Joseph", "Akeal Hosein",
            "Brandon King", "Romario Shepherd", "Kyle Mayers", "Evin Lewis",
            "Gudakesh Motie", "Johnson Charles", "Obed McCoy",
        ],
    },
    "bangladesh": {
        "name": "Bangladesh",
        "league": "international",
        "logo": "🌏",
        "players": [
            "Litton Das", "Nurul Hasan", "Parvez Hossain Emon", "Tanzid Hasan",
"Towhid Hridoy", "Mahedi Hasan", "Nasum Ahmed", "Rishad Hossain",
"Saif Hassan", "Shamim Hossain", "Abdul Gaffar Saqlain", "Mustafizur Rahman",
"Nahid Rana", "Shoriful Islam", "Taskin Ahmed",
        ],
    },
    "afghanistan": {
        "name": "Afghanistan",
        "league": "international",
        "logo": "🌏",
        "players": [
           "Rashid Khan", "Noor Ahmad", "Abdullah Ahmadzai", "Sediqullah Atal",
"Fazalhaq Farooqi", "Rahmanullah Gurbaz", "Naveen-ul-Haq", "Mohammad Ishaq",
"Shahidullah Kamal", "Mohammad Nabi", "Gulbadin Naib", "Azmatullah Omarzai",
"Mujeeb Ur Rahman", "Darwish Rasooli", "Ibrahim Zadran",
        ],
    },
    "mumbai_indians": {
        "name": "Mumbai Indians",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Rohit Sharma", "Suryakumar Yadav", "Ishan Kishan", "Hardik Pandya",
            "Tilak Varma", "Tim David", "Gerald Coetzee", "Jasprit Bumrah",
            "Naman Dhir", "Piyush Chawla", "Romario Shepherd", "Akash Madhwal",
            "Will Jacks", "Arjun Tendulkar", "Dewald Brevis",
        ],
    },
    "chennai_super_kings": {
        "name": "Chennai Super Kings",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Ruturaj Gaikwad", "Devon Conway", "Shivam Dube", "Ravindra Jadeja",
            "MS Dhoni", "Matheesha Pathirana", "Deepak Chahar", "Sam Curran",
            "Ravichandran Ashwin", "Ajinkya Rahane", "Shardul Thakur", "Anshul Kamboj",
            "Sameer Rizvi", "Moeen Ali", "Mustafizur Rahman",
        ],
    },
    "royal_challengers_bengaluru": {
        "name": "Royal Challengers Bengaluru",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Virat Kohli", "Faf du Plessis", "Rajat Patidar", "Glenn Maxwell",
            "Cameron Green", "Dinesh Karthik", "Mohammed Siraj", "Yash Dayal",
            "Karn Sharma", "Swapnil Singh", "Reece Topley", "Mahipal Lomror",
            "Will Jacks", "Saurav Chauhan", "Vijaykumar Vyshak",
        ],
    },
    "kolkata_knight_riders": {
        "name": "Kolkata Knight Riders",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Shreyas Iyer", "Andre Russell", "Sunil Narine", "Venkatesh Iyer",
            "Rinku Singh", "Mitchell Starc", "Harshit Rana", "Varun Chakravarthy",
            "Phil Salt", "Rachin Ravindra", "Ramandeep Singh", "Nitish Rana",
            "Angkrish Raghuvanshi", "Suyash Sharma", "Vaibhav Arora",
        ],
    },
    "rajasthan_royals": {
        "name": "Rajasthan Royals",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Sanju Samson", "Yashasvi Jaiswal", "Riyan Parag", "Dhruv Jurel",
            "Shimron Hetmyer", "Jos Buttler", "Ravichandran Ashwin", "Trent Boult",
            "Yuzvendra Chahal", "Sandeep Sharma", "Tanush Kotian", "Keshav Maharaj",
            "Nandre Burger", "Rovman Powell", "Donovan Ferreira",
        ],
    },
    "sunrisers_hyderabad": {
        "name": "Sunrisers Hyderabad",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Pat Cummins", "Travis Head", "Abhishek Sharma", "Heinrich Klaasen",
            "Nitish Kumar Reddy", "Bhuvneshwar Kumar", "T Natarajan", "Rahul Chahar",
            "Aiden Markram", "Mayank Agarwal", "Washington Sundar", "Marco Jansen",
            "Sanvir Singh", "Abdul Samad", "Glenn Phillips",
        ],
    },
    "delhi_capitals": {
        "name": "Delhi Capitals",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Rishabh Pant", "David Warner", "Axar Patel", "Prithvi Shaw",
            "Kuldeep Yadav", "Tristan Stubbs", "Jake Fraser-McGurk", "Anrich Nortje",
            "Mukesh Kumar", "Khaleel Ahmed", "Mitchell Marsh", "Ishant Sharma",
            "Abishek Porel", "Ricky Bhui", "Yash Dhull",
        ],
    },
    "gujarat_titans": {
        "name": "Gujarat Titans",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Shubman Gill", "Sai Sudharsan", "David Miller", "Rahul Tewatia",
            "Rashid Khan", "Kagiso Rabada", "Mohammed Shami", "Wriddhiman Saha",
            "Vijay Shankar", "Sai Kishore", "Joshua Little", "Noor Ahmad",
            "Shahrukh Khan", "Mohit Sharma", "Azmatullah Omarzai",
        ],
    },
    "lucknow_super_giants": {
        "name": "Lucknow Super Giants",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "KL Rahul", "Nicholas Pooran", "Marcus Stoinis", "Ravi Bishnoi",
            "Krunal Pandya", "Quinton de Kock", "Ayush Badoni", "Deepak Hooda",
            "Mayank Yadav", "Naveen-ul-Haq", "Mohsin Khan", "Yash Thakur",
            "Devdutt Padikkal", "Arshin Kulkarni", "Ashton Turner",
        ],
    },
    "punjab_kings": {
        "name": "Punjab Kings",
        "league": "ipl",
        "logo": "🏆",
        "players": [
            "Shikhar Dhawan", "Sam Curran", "Jonny Bairstow", "Liam Livingstone",
            "Arshdeep Singh", "Harpreet Brar", "Jitesh Sharma", "Shashank Singh",
            "Rahul Chahar", "Harshal Patel", "Prabhsimran Singh", "Ashutosh Sharma",
            "Nathan Ellis", "Sikandar Raza", "Matthew Short",
        ],
    },
}

PITCHES = {
    "balanced": {"name": "Balanced", "modifiers": {}},
    "batting": {
        "name": "Batting paradise",
        "modifiers": {"wicket": 0.8, "dot": 0.85, "four": 1.2, "six": 1.2},
    },
    "green": {
        "name": "Green seamer",
        "modifiers": {"wicket": 1.3, "dot": 1.15, "four": 0.85, "six": 0.85},
    },
    "spin": {
        "name": "Turning track",
        "modifiers": {"wicket": 1.2, "dot": 1.15, "two": 1.05, "four": 0.9, "six": 0.8},
    },
}

# ---------------------------------------------------------------------------
# Player roles (used by the XI selector for both International and IPL squads)
#   BAT  = specialist batter      AR = all-rounder
#   BOWL = specialist bowler      WK = wicketkeeper
# Roles are starter assignments, keyed by player name; edit them freely.
# Anyone not listed here is treated as a batter.
# ---------------------------------------------------------------------------
ROLE_CODES = ("BAT", "AR", "BOWL", "WK")

ROLES = {
    # --- India ---
    "Shreyas Iyer": "BAT", "Tilak Varma": "BAT", "Abhishek Sharma": "AR",
    "Vaibhav Sooryavanshi": "BAT", "Ishan Kishan": "WK", "Sanju Samson": "WK",
    "Rinku Singh": "BAT", "Shivam Dube": "AR", "Axar Patel": "AR",
    "Washington Sundar": "AR", "Nitish Kumar Reddy": "AR", "Kuldeep Yadav": "BOWL",
    "Ravi Bishnoi": "BOWL", "Arshdeep Singh": "BOWL", "Prince Yadav": "BOWL",
    "Mayank Yadav": "BOWL",
    # --- Australia ---
    "Mitchell Marsh": "AR", "Xavier Bartlett": "BOWL", "Mahli Beardman": "BOWL",
    "Nikhil Chaudhary": "AR", "Tim David": "BAT", "Joel Davies": "BAT",
    "Jack Edwards": "AR", "Nathan Ellis": "BOWL", "Jake Fraser-McGurk": "BAT",
    "Sam Harper": "WK", "Spencer Johnson": "BOWL", "Mitchell Owen": "AR",
    "Lachlan Shaw": "BAT", "Adam Zampa": "BOWL",
    # --- England ---
    "Harry Brook": "BAT", "Tom Banton": "WK", "James Coles": "AR",
    "Jordan Cox": "WK", "Henry Crocombe": "BOWL", "Sam Curran": "AR",
    "Liam Dawson": "AR", "Aneurin Donald": "BAT", "Eddie Jack": "BOWL",
    "Will Jacks": "AR", "Jamie Overton": "AR", "Adil Rashid": "BOWL",
    "Thomas Rew": "WK", "Phil Salt": "WK", "Luke Wood": "BOWL",
    # --- Pakistan ---
    "Sahibzada Farhan": "BAT", "Abdul Samad": "BAT", "Fakhar Zaman": "BAT",
    "Hasan Nawaz": "BAT", "Khawaja Nafay": "WK", "Arafat Minhas": "AR",
    "Maaz Sadaqat": "BAT", "Mohammad Imran": "BOWL", "Saim Ayub": "AR",
    "Shadab Khan": "AR", "Abrar Ahmed": "BOWL", "Naseem Shah": "BOWL",
    "Razaullah": "BOWL", "Salman Mirza": "BOWL", "Sufyan Moqim": "BOWL",
    # --- New Zealand ---
    "Mitchell Santner": "AR", "Finn Allen": "BAT", "Mark Chapman": "BAT",
    "Devon Conway": "WK", "Jacob Duffy": "BOWL", "Lockie Ferguson": "BOWL",
    "Matt Henry": "BOWL", "Kyle Jamieson": "BOWL", "Cole McConchie": "AR",
    "Daryl Mitchell": "AR", "James Neesham": "AR", "Glenn Phillips": "BAT",
    "Rachin Ravindra": "AR", "Tim Seifert": "WK", "Ish Sodhi": "BOWL",
    # --- South Africa ---
    "Aiden Markram": "BAT", "Corbin Bosch": "AR", "Dewald Brevis": "BAT",
    "Quinton de Kock": "WK", "Marco Jansen": "AR", "George Linde": "AR",
    "Keshav Maharaj": "BOWL", "Kwena Maphaka": "BOWL", "David Miller": "BAT",
    "Lungi Ngidi": "BOWL", "Anrich Nortje": "BOWL", "Kagiso Rabada": "BOWL",
    "Ryan Rickelton": "WK", "Jason Smith": "AR", "Tristan Stubbs": "BAT",
    # --- Sri Lanka ---
    "Kusal Mendis": "WK", "Kamil Mishara": "BAT", "Sineth Jayawardena": "AR",
    "Lahiru Udara": "BAT", "Sahan Arachchige": "AR", "Kamindu Mendis": "AR",
    "Dasun Shanaka": "AR", "Chamindu Wickramasinghe": "AR",
    "Dushmantha Chameera": "BOWL", "Binura Fernando": "BOWL",
    "Eshan Malinga": "BOWL", "Maheesh Theekshana": "BOWL", "Nuwan Thushara": "BOWL",
    "Vijayakanth Viyaskanth": "BOWL", "Dunith Wellalage": "AR",
    # --- West Indies ---
    "Nicholas Pooran": "WK", "Shai Hope": "WK", "Andre Russell": "AR",
    "Jason Holder": "AR", "Rovman Powell": "BAT", "Shimron Hetmyer": "BAT",
    "Alzarri Joseph": "BOWL", "Akeal Hosein": "BOWL", "Brandon King": "BAT",
    "Romario Shepherd": "AR", "Kyle Mayers": "AR", "Evin Lewis": "BAT",
    "Gudakesh Motie": "BOWL", "Johnson Charles": "WK", "Obed McCoy": "BOWL",
    # --- Bangladesh ---
    "Litton Das": "WK", "Nurul Hasan": "WK", "Parvez Hossain Emon": "BAT",
    "Tanzid Hasan": "BAT", "Towhid Hridoy": "BAT", "Mahedi Hasan": "AR",
    "Nasum Ahmed": "BOWL", "Rishad Hossain": "AR", "Saif Hassan": "BAT",
    "Shamim Hossain": "AR", "Abdul Gaffar Saqlain": "AR", "Mustafizur Rahman": "BOWL",
    "Nahid Rana": "BOWL", "Shoriful Islam": "BOWL", "Taskin Ahmed": "BOWL",
    # --- Afghanistan ---
    "Rashid Khan": "AR", "Noor Ahmad": "BOWL", "Abdullah Ahmadzai": "BAT",
    "Sediqullah Atal": "BAT", "Fazalhaq Farooqi": "BOWL", "Rahmanullah Gurbaz": "WK",
    "Naveen-ul-Haq": "BOWL", "Mohammad Ishaq": "WK", "Shahidullah Kamal": "BAT",
    "Mohammad Nabi": "AR", "Gulbadin Naib": "AR", "Azmatullah Omarzai": "AR",
    "Mujeeb Ur Rahman": "BOWL", "Darwish Rasooli": "AR", "Ibrahim Zadran": "BAT",
    # --- IPL: Mumbai Indians ---
    "Rohit Sharma": "BAT", "Suryakumar Yadav": "BAT", "Hardik Pandya": "AR",
    "Gerald Coetzee": "BOWL", "Jasprit Bumrah": "BOWL", "Naman Dhir": "AR",
    "Piyush Chawla": "BOWL", "Akash Madhwal": "BOWL", "Arjun Tendulkar": "AR",
    # --- IPL: Chennai Super Kings ---
    "Ruturaj Gaikwad": "BAT", "Ravindra Jadeja": "AR", "MS Dhoni": "WK",
    "Matheesha Pathirana": "BOWL", "Deepak Chahar": "BOWL",
    "Ravichandran Ashwin": "AR", "Ajinkya Rahane": "BAT", "Shardul Thakur": "AR",
    "Anshul Kamboj": "BOWL", "Sameer Rizvi": "BAT", "Moeen Ali": "AR",
    # --- IPL: Royal Challengers Bengaluru ---
    "Virat Kohli": "BAT", "Faf du Plessis": "BAT", "Rajat Patidar": "BAT",
    "Glenn Maxwell": "AR", "Cameron Green": "AR", "Dinesh Karthik": "WK",
    "Mohammed Siraj": "BOWL", "Yash Dayal": "BOWL", "Karn Sharma": "BOWL",
    "Swapnil Singh": "AR", "Reece Topley": "BOWL", "Mahipal Lomror": "AR",
    "Saurav Chauhan": "BAT", "Vijaykumar Vyshak": "BOWL",
    # --- IPL: Kolkata Knight Riders ---
    "Sunil Narine": "AR", "Venkatesh Iyer": "AR", "Mitchell Starc": "BOWL",
    "Harshit Rana": "BOWL", "Varun Chakravarthy": "BOWL", "Ramandeep Singh": "AR",
    "Nitish Rana": "BAT", "Angkrish Raghuvanshi": "BAT", "Suyash Sharma": "BOWL",
    "Vaibhav Arora": "BOWL",
    # --- IPL: Rajasthan Royals ---
    "Yashasvi Jaiswal": "BAT", "Riyan Parag": "AR", "Dhruv Jurel": "WK",
    "Jos Buttler": "WK", "Trent Boult": "BOWL", "Yuzvendra Chahal": "BOWL",
    "Sandeep Sharma": "BOWL", "Tanush Kotian": "AR", "Nandre Burger": "BOWL",
    "Donovan Ferreira": "WK",
    # --- IPL: Sunrisers Hyderabad ---
    "Pat Cummins": "BOWL", "Travis Head": "BAT", "Heinrich Klaasen": "WK",
    "Bhuvneshwar Kumar": "BOWL", "T Natarajan": "BOWL", "Rahul Chahar": "BOWL",
    "Mayank Agarwal": "BAT", "Sanvir Singh": "AR",
    # --- IPL: Delhi Capitals ---
    "Rishabh Pant": "WK", "David Warner": "BAT", "Prithvi Shaw": "BAT",
    "Mukesh Kumar": "BOWL", "Khaleel Ahmed": "BOWL", "Ishant Sharma": "BOWL",
    "Abishek Porel": "WK", "Ricky Bhui": "BAT", "Yash Dhull": "BAT",
    # --- IPL: Gujarat Titans ---
    "Shubman Gill": "BAT", "Sai Sudharsan": "BAT", "Rahul Tewatia": "AR",
    "Mohammed Shami": "BOWL", "Wriddhiman Saha": "WK", "Vijay Shankar": "AR",
    "Sai Kishore": "BOWL", "Joshua Little": "BOWL", "Shahrukh Khan": "BAT",
    "Mohit Sharma": "BOWL",
    # --- IPL: Lucknow Super Giants ---
    "KL Rahul": "WK", "Marcus Stoinis": "AR", "Krunal Pandya": "AR",
    "Ayush Badoni": "BAT", "Deepak Hooda": "AR", "Mohsin Khan": "BOWL",
    "Yash Thakur": "BOWL", "Devdutt Padikkal": "BAT", "Arshin Kulkarni": "AR",
    "Ashton Turner": "BAT",
    # --- IPL: Punjab Kings ---
    "Shikhar Dhawan": "BAT", "Jonny Bairstow": "WK", "Liam Livingstone": "AR",
    "Harpreet Brar": "AR", "Jitesh Sharma": "WK", "Shashank Singh": "BAT",
    "Harshal Patel": "BOWL", "Prabhsimran Singh": "WK", "Ashutosh Sharma": "BAT",
    "Sikandar Raza": "AR", "Matthew Short": "AR",
}


def player_role(name: str) -> str:
    """Return BAT / AR / BOWL / WK for a player (batter if unknown)."""
    return ROLES.get(name, "BAT")


# ---------------------------------------------------------------------------
# Player ratings: separate BATTING and BOWLING ratings (1-99).
# Stars have hand-set ratings below; everyone else gets a role-based rating with
# a small stable per-player variation, so no two players are exactly alike.
# They are game values, not real statistics; edit them freely.
# ---------------------------------------------------------------------------
PLAYER_RATINGS = {
    # name: (batting, bowling)
    "Virat Kohli": (93, 10), "Rohit Sharma": (89, 8), "Suryakumar Yadav": (91, 10),
    "Hardik Pandya": (80, 80), "Jasprit Bumrah": (22, 97), "MS Dhoni": (78, 5),
    "Ravindra Jadeja": (74, 86), "Ruturaj Gaikwad": (85, 5), "Jos Buttler": (88, 5),
    "Yashasvi Jaiswal": (86, 5), "Shubman Gill": (87, 5), "Rashid Khan": (62, 94),
    "Sunil Narine": (70, 91), "Andre Russell": (86, 78), "Glenn Maxwell": (84, 66),
    "Marcus Stoinis": (78, 68), "Pat Cummins": (55, 90), "Travis Head": (90, 18),
    "Heinrich Klaasen": (91, 5), "Rishabh Pant": (85, 5), "KL Rahul": (85, 5),
    "Mitchell Starc": (30, 91), "Kagiso Rabada": (28, 92), "Trent Boult": (22, 88),
    "Mohammed Shami": (20, 88), "Mohammed Siraj": (20, 85), "Yuzvendra Chahal": (15, 84),
    "Nicholas Pooran": (88, 5), "Quinton de Kock": (86, 5), "Phil Salt": (87, 5),
    "Harry Brook": (86, 20), "Aiden Markram": (80, 52), "Mitchell Marsh": (80, 62),
    "Adam Zampa": (15, 84), "Adil Rashid": (20, 82), "Ravichandran Ashwin": (52, 83),
    "Jake Fraser-McGurk": (85, 10), "Tim David": (84, 15), "Liam Livingstone": (82, 66),
    "Sam Curran": (72, 77), "Will Jacks": (80, 58), "Mitchell Santner": (55, 83),
    "Mustafizur Rahman": (20, 85), "Naseem Shah": (15, 84), "Shadab Khan": (68, 75),
    "Saim Ayub": (79, 50), "Fakhar Zaman": (81, 5), "Keshav Maharaj": (30, 81),
    "Marco Jansen": (66, 83), "Anrich Nortje": (20, 88), "Lungi Ngidi": (18, 84),
    "Matheesha Pathirana": (15, 87), "Lockie Ferguson": (15, 85),
    "Dushmantha Chameera": (20, 81), "Maheesh Theekshana": (15, 84),
    "Shimron Hetmyer": (82, 5), "Rovman Powell": (78, 10), "Jason Holder": (62, 83),
    "Akeal Hosein": (30, 79), "Alzarri Joseph": (25, 81), "Noor Ahmad": (15, 83),
    "Mujeeb Ur Rahman": (15, 81), "Rahmanullah Gurbaz": (82, 5), "Ibrahim Zadran": (78, 8),
    "Mohammad Nabi": (66, 73), "Azmatullah Omarzai": (69, 71), "Litton Das": (80, 5),
    "Taskin Ahmed": (18, 81), "Mahedi Hasan": (55, 73), "Rishad Hossain": (50, 73),
    "Daryl Mitchell": (82, 46), "Devon Conway": (84, 5), "Glenn Phillips": (82, 40),
    "Rachin Ravindra": (77, 63), "James Neesham": (75, 66), "Finn Allen": (84, 5),
    "Matt Henry": (20, 85), "Harpreet Brar": (45, 71), "Harshal Patel": (30, 83),
    "Arshdeep Singh": (25, 87), "Bhuvneshwar Kumar": (30, 85), "T Natarajan": (12, 84),
    "Varun Chakravarthy": (10, 87), "Harshit Rana": (25, 79), "Axar Patel": (72, 81),
    "Washington Sundar": (66, 77), "Kuldeep Yadav": (28, 89), "Ravi Bishnoi": (22, 83),
    "Venkatesh Iyer": (77, 53), "Ramandeep Singh": (66, 51), "Rahul Tewatia": (73, 56),
    "Sai Sudharsan": (84, 5), "Devdutt Padikkal": (79, 5), "Ayush Badoni": (74, 15),
    "Krunal Pandya": (62, 73), "Deepak Hooda": (68, 53), "Moeen Ali": (75, 67),
    "Shardul Thakur": (50, 77), "Deepak Chahar": (30, 81), "Ajinkya Rahane": (77, 5),
    "Dinesh Karthik": (77, 3), "Rajat Patidar": (80, 3), "Faf du Plessis": (83, 5),
    "Cameron Green": (75, 73), "Reece Topley": (15, 79), "Yash Dayal": (15, 77),
    "Shreyas Iyer": (85, 10), "Tilak Varma": (84, 36), "Abhishek Sharma": (87, 49),
    "Shivam Dube": (81, 51), "Nitish Kumar Reddy": (74, 63), "Sanju Samson": (85, 5),
    "Rinku Singh": (84, 10), "Ishan Kishan": (81, 5), "Mayank Yadav": (20, 85),
    "Kyle Jamieson": (45, 83), "Corbin Bosch": (55, 76), "David Miller": (84, 5),
    "Tristan Stubbs": (80, 12), "Dewald Brevis": (79, 25), "Nathan Ellis": (20, 82),
    "Spencer Johnson": (15, 81), "Naveen-ul-Haq": (18, 80), "Fazalhaq Farooqi": (14, 81),
}

_ROLE_BASE_RATINGS = {
    "BAT": (72, 15),
    "WK": (72, 8),
    "AR": (68, 62),
    "BOWL": (28, 70),
}


def _stable_jitter(salt: str, name: str, spread: int) -> int:
    """Deterministic per-player variation (crc32, so it never changes between runs)."""
    return zlib.crc32(f"{salt}:{name}".encode("utf-8")) % (2 * spread + 1) - spread


def player_ratings(name: str) -> tuple[int, int]:
    """Return (batting_rating, bowling_rating), each between 1 and 99."""
    if name in PLAYER_RATINGS:
        return PLAYER_RATINGS[name]
    bat_base, bowl_base = _ROLE_BASE_RATINGS[player_role(name)]
    bat = bat_base + _stable_jitter("bat", name, 6)
    bowl = bowl_base + _stable_jitter("bowl", name, 6)
    return max(1, min(99, bat)), max(1, min(99, bowl))


def bat_rating(name: str) -> int:
    return player_ratings(name)[0]


def bowl_rating(name: str) -> int:
    return player_ratings(name)[1]
