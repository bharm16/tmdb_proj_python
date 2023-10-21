# Import required libraries
import threading
import time

from queue import Queue, Empty

import tmdb
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user

from nextreel.scripts.account import Account
from nextreel.scripts.db_config_scripts import db_config, user_db_config
from nextreel.scripts.get_user_account import get_user_by_id, get_all_watched_movie_details_by_user, \
    get_all_movies_in_watchlist
from nextreel.scripts.log_movie_to_account import update_title_basics_if_empty
from nextreel.scripts.movie import Movie
from nextreel.scripts.person import Person
from nextreel.scripts.set_filters_for_nextreel_backend import ImdbRandomMovieFetcher, extract_movie_filter_criteria
from nextreel.scripts.tmdb_data import get_tmdb_id_by_tconst, get_movie_info_by_tmdb_id

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'some_random_secret_key'  # IMPORTANT: Change this in production

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)

# Variable to determine whether a user should be logged out when the home page loads
should_logout_on_home_load = True

# Define global variables to hold the movie fetcher and criteria
global_movie_fetcher = ImdbRandomMovieFetcher(db_config)
global_criteria = {}  # Start with empty criteria; can be updated dynamically

# Initialize a global queue to hold movie data
movie_queue = Queue(maxsize=3)

# Assuming ImdbRandomMovieFetcher is imported or defined above


# Set your TMDb API key
tmdb.API_KEY = '1ce9398920594a5521f0d53e9b33c52f'


def populate_movie_queue():
    global global_movie_fetcher, global_criteria  # Use global variables
    watched_movies = set()
    watchlist_movies = set()

    while True:
        if current_user and current_user.is_authenticated:
            watched_movies = set([movie['tconst'] for movie in get_all_watched_movie_details_by_user(current_user.id)])
            watchlist_movies = set([movie['tconst'] for movie in get_all_movies_in_watchlist(current_user.id)])

        if movie_queue.qsize() < 2:
            row = global_movie_fetcher.fetch_random_movie(global_criteria)  # Use global criteria
            tconst = row['tconst'] if row else None

            if tconst and (tconst not in watched_movies) and (tconst not in watchlist_movies):
                movie = Movie(tconst, db_config)
                movie_data_imdb = movie.get_movie_data()

                # Fetch TMDb ID using IMDb tconst
                tmdb_id = get_tmdb_id_by_tconst(tconst)  # Using the imported function here

                movie_data_tmdb = get_movie_info_by_tmdb_id(tmdb_id)
                print(movie_data_tmdb)

                # If a TMDb ID is found, you can fetch more data from TMDb or do whatever you need to do
                if tmdb_id:
                    movie_data_tmdb = get_movie_info_by_tmdb_id(tmdb_id)  # Replace with your actual TMDb fetching function
                    backdrop_path = movie_data_tmdb.get('backdrop_path', '')  # Replace with your actual logic
                    movie_data_imdb['backdrop_path'] = backdrop_path  # Add backdrop_path to the dictionary

                movie_data = {
                    'IMDb': movie_data_imdb,
                    'TMDb': movie_data_tmdb
                }

            movie_queue.put(movie_data_imdb)
            update_title_basics_if_empty(tconst, movie_data_imdb['plot'], movie_data_imdb['poster_url'],
                                         movie_data_imdb['languages'], db_config)

        time.sleep(1)


# Don't forget to import other required modules and functions


# Start a thread to populate the movie queue
# Start a background thread to populate the movie queue
populate_thread = threading.Thread(target=populate_movie_queue)
populate_thread.daemon = True  # Set the thread as a daemon
populate_thread.start()


@app.route('/account_settings')
@login_required
def account_settings():
    print("Current user's email:", current_user.email)

    # Render the account settings template
    return render_template('user_account_settings.html')


from flask import request, render_template, flash
from flask_login import login_required, current_user
from nextreel.scripts.sort_and_filter import sort_movies, get_filtered_watched_movies  # Import the sorting function


@app.route('/watched_movies')
@login_required
def watched_movies():
    # Initialize Account object with current user's details
    current_account = Account(id=current_user.id, username=current_user.username, email=current_user.email)

    # Fetch all watched movie details for the current user
    watched_movie_details = current_account.get_watched_movies_by_user(current_account.id)

    imdb_score_min = request.args.get('imdb_score_min', default=None, type=float)
    imdb_score_max = request.args.get('imdb_score_max', default=None, type=float)

    num_votes_min = request.args.get('num_votes_min', default=None, type=int)

    genres = request.args.getlist('genres[]')  # Fetch multiple genre options
    language = request.args.get('selectedLanguage', default=None, type=str)

    # Fetch all watched movie details for the current user with filters
    watched_movie_details = get_filtered_watched_movies(
        user_db_config,
        current_user.id,
        imdb_score_min=imdb_score_min,
        imdb_score_max=imdb_score_max,

        num_votes_min=num_votes_min,
        genres=genres,
        language=language
    )

    # Get the sorting criteria from query parameters
    sort_by = request.args.get('sort_by', default='tconst', type=str)

    # Sort the movies using the imported function
    watched_movie_details = sort_movies(watched_movie_details, sort_by)

    if watched_movie_details is None or len(watched_movie_details) == 0:
        flash("No watched movies found for this user.")

    return render_template('watched_movies.html', watched_movie_details=watched_movie_details)


@login_manager.user_loader
def load_user(user_id):
    # Query to fetch user details from the database
    # user_data = execute_query(user_db_config, "SELECT * FROM users WHERE id=%s", (user_id,))
    user_data = get_user_by_id(user_id)
    # If user data exists, return a User object
    if user_data:
        return Account(id=user_data['id'], username=user_data['username'], email=user_data['email'])  # Add email here
    # Otherwise, return None


# Declare a global variable to store the last displayed movie
global last_displayed_movie

# Initialize two lists to act as stacks for previous and future movies

future_movies_stack = []
previous_movies_stack = []
current_displayed_movie = None


@app.route('/')
def home():
    return render_template('home.html')

    # global should_logout_on_home_load
    # Logout the user if the flag is set
    # if should_logout_on_home_load:
    #     logout_user()
    #     should_logout_on_home_load = False

    # Fetch a movie from the global queue
    # (consider adding additional logic here to ensure the movie is appropriate for the user)
    # movie_data = movie_queue.get()

    # Update the global variable with the fetched movie data
    # global last_displayed_movie
    # last_displayed_movie = movie_data

    # Render the home page with the fetched movie data
    # return render_template('home.html', movie=movie_data, current_user=current_user)


# Declare global stacks and variables
previous_movies_stack = []
future_movies_stack = []
current_displayed_movie = None


@app.route('/movie')
def movie():
    global current_displayed_movie
    # Fetch the next movie from the queue
    current_movie_data = movie_queue.get()

    # Update the global current_displayed_movie
    current_displayed_movie = current_movie_data

    # Append the current displayed movie to the previous_movies_stack
    previous_movies_stack.append(current_movie_data)

    # Render the movie template, also passing the length of previous_movies_stack for UI control
    return render_template('movie.html',
                           movie=current_movie_data,
                           current_user=current_user,
                           previous_count=len(previous_movies_stack))


@app.route('/previous_movie', methods=['GET', 'POST'])
def previous_movie():
    global current_displayed_movie, future_movies_stack  # Declare global variables

    # Append the current displayed movie to the future_movies_stack
    if current_displayed_movie is not None:
        future_movies_stack.append(current_displayed_movie)

    # Pop the previous movie from previous_movies_stack
    previous_movie_data = previous_movies_stack.pop()

    # Update the current displayed movie
    current_displayed_movie = previous_movie_data

    # Render the movie template, also passing the length of previous_movies_stack for UI control
    return render_template('movie.html',
                           movie=previous_movie_data,
                           current_user=current_user,
                           previous_count=len(previous_movies_stack))


@app.route('/next_movie', methods=['GET', 'POST'])
def next_movie():
    global current_displayed_movie  # Declare global variables

    # Append the current displayed movie to the previous_movies_stack
    if current_displayed_movie is not None:
        previous_movies_stack.append(current_displayed_movie)

    next_movie_data = None

    # Check if future_movies_stack has any movies to go forward to
    if future_movies_stack:
        next_movie_data = future_movies_stack.pop()
    else:
        # If no future movies, get a new movie from the queue
        next_movie_data = movie_queue.get()

    # Update the current displayed movie
    current_displayed_movie = next_movie_data

    # Render the movie template, also passing the length of previous_movies_stack for UI control
    return render_template('movie.html',
                           movie=next_movie_data,
                           current_user=current_user,
                           previous_count=len(previous_movies_stack))


# Assuming current_user is an instance of Account
@app.route('/seen_it', methods=['POST'])
@login_required
def seen_it():
    global current_displayed_movie
    if current_displayed_movie:
        tconst = current_displayed_movie.get("imdb_id")
        current_user.log_movie_to_user_account(current_user.id, current_user.username, tconst, current_displayed_movie,
                                               user_db_config)
        return redirect(url_for('movie'))
    else:
        return jsonify({'status': 'failure', 'message': 'No movies in the queue'}), 400


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Call the class method, passing in db_config explicitly
        user_data = Account.login_user(username, password, user_db_config)

        if user_data:
            # Create an Account instance for this user
            user = Account(id=user_data['id'], username=user_data['username'], email=user_data['email'])
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash("Invalid username or password")

    return render_template('user_login.html')


# Route for logout
@app.route('/logout')
@login_required  # Require the user to be logged in to access this route
def logout():
    # Log the user out
    logout_user()
    # Redirect to the login page
    return redirect(url_for('login'))


# Route for user registration
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']

        result = Account.register_user(username, email, password)

        if result == "Username already exists.":
            flash("Username already exists.")
            return render_template('create_account_form.html')

        flash("ShowModal")
        return redirect(url_for('login'))

    return render_template('create_account_form.html')


# Route for setting filters
@app.route('/setFilters')
def set_filters():
    # Render the filter settings template
    return render_template('set_filters.html')


@app.route('/filtered_movie', methods=['POST'])
def filtered_movie_endpoint():
    global global_movie_fetcher, global_criteria  # Declare global variables

    # Extract new filter criteria from the form
    new_criteria = extract_movie_filter_criteria(request.form)

    print("Extracted criteria:", new_criteria)

    # Update global criteria
    global_criteria = new_criteria

    # Empty the existing movie queue to remove movies that don't match new criteria
    while not movie_queue.empty():
        try:
            movie_queue.get_nowait()
        except Empty:
            break

    # Fetch a random movie based on the updated global criteria
    row = global_movie_fetcher.fetch_random_movie(global_criteria)

    # If no movies found, return an error message
    if not row:
        return "No movies found based on the given criteria."

    # Create a Movie instance and fetch the movie data
    movie = Movie(row['tconst'], db_config)

    # Fetch and generate detailed movie information
    movie_data = movie.get_movie_data()

    # Render the template with the filtered movie
    # return render_template('filtered_movies.html', movie=movie_data)
    return render_template('movie.html', movie=movie_data)


@app.route('/actor/<actor_name>', methods=['GET'])
def get_movies_by_actor(actor_name):
    start_time = time.time()  # Record the start time

    # Create a Person object
    actor = Person(db_config, actor_name)

    # Use the Person object to fetch actor's details
    fetched_actor = actor.actor_info

    if fetched_actor is None:
        return "Actor not found", 404

    # Convert the actor information to a dictionary
    actor_dict = fetched_actor.data

    # Fetch the actor's filmography (this assumes that 'filmography' is a key in actor_dict)
    actor_filmography = actor_dict.get('filmography', {})

    end_time = time.time()  # Record the end time
    print(f"Time taken for database queries: {end_time - start_time} seconds")

    # Render a template to display the actor's details and filmography
    return render_template('actor_movies.html', actor_dict=actor_dict, actor_filmography=actor_filmography,
                           actor_name=actor_name)


@app.route('/add_to_watchlist', methods=['POST'])
@login_required
def add_to_watchlist():
    global current_displayed_movie  # Consider using a different state management approach
    if current_displayed_movie:
        tconst = current_displayed_movie.get("imdb_id")

        # Assuming current_user is an instance of Account
        current_user.add_movie_to_watchlist(current_user.id, current_user.username, tconst, current_displayed_movie,
                                            user_db_config)

        return redirect(url_for('movie'))
    else:
        return jsonify({'status': 'failure', 'message': 'No movies in the queue'}), 400


@app.route('/user_watch_list')
@login_required
def user_watch_list():
    watchlist_movies = get_all_movies_in_watchlist(current_user.id)
    return render_template('user_watchlist.html', watchlist_movies=watchlist_movies)


if __name__ == "__main__":
    # Run the Flask app in debug mode (change this in production)
    app.run(debug=True)
