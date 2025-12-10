import pytest
import os
import tempfile
from app import app, db, Submission, DailyTweet, DcLike
from io import BytesIO


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['WTF_CSRF_ENABLED'] = False
    
    with tempfile.TemporaryDirectory() as tmpdir:
        app.config['UPLOAD_FOLDER'] = tmpdir
        
        with app.test_client() as client:
            with app.app_context():
                db.create_all()
            yield client
            with app.app_context():
                db.drop_all()


def test_index_route(client):
    """Test the index page loads successfully."""
    response = client.get('/')
    assert response.status_code == 200


def test_daily_route(client):
    """Test the daily upload page loads successfully."""
    response = client.get('/daily')
    assert response.status_code == 200


def test_gm_login_page(client):
    """Test the GM login page loads successfully."""
    response = client.get('/gm/login')
    assert response.status_code == 200


def test_gm_login_success(client):
    """Test GM login with valid credentials."""
    response = client.post('/gm/login', data={
        'username': os.getenv('ADMIN1_USERNAME', 'gm1'),
        'password': os.getenv('ADMIN1_PASSWORD', 'gm1password')
    }, follow_redirects=True)
    assert response.status_code == 200


def test_gm_login_failure(client):
    """Test GM login with invalid credentials."""
    response = client.post('/gm/login', data={
        'username': 'invalid',
        'password': 'wrong'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert '帳號或密碼錯誤' in response.get_data(as_text=True) or response.request.path == '/gm/login'


def test_submit_missing_game_id(client):
    """Test submission without game_id."""
    response = client.post('/submit', data={}, follow_redirects=True)
    assert response.status_code == 200


def test_daily_upload_missing_game_id(client):
    """Test daily upload without game_id."""
    response = client.post('/daily_upload', data={}, follow_redirects=True)
    assert response.status_code == 200


def test_database_models():
    """Test that database models can be instantiated."""
    submission = Submission(
        game_id='test123',
        prereg_1='path1.jpg',
        prereg_2='path2.jpg',
        discord_1='path3.jpg',
        discord_2='path4.jpg'
    )
    assert submission.game_id == 'test123'
    
    tweet = DailyTweet(
        game_id='test456',
        image_path='tweet.jpg'
    )
    assert tweet.game_id == 'test456'
    
    dclike = DcLike(
        game_id='test789',
        image_path='like.jpg'
    )
    assert dclike.game_id == 'test789'


def test_allowed_file():
    """Test the allowed_file function."""
    from app import allowed_file
    
    assert allowed_file('test.png') == True
    assert allowed_file('test.jpg') == True
    assert allowed_file('test.jpeg') == True
    assert allowed_file('test.gif') == True
    assert allowed_file('test.webp') == True
    assert allowed_file('test.txt') == False
    assert allowed_file('test.exe') == False
    assert allowed_file('test') == False


def test_gm_dashboard_requires_auth(client):
    """Test that GM dashboard requires authentication."""
    response = client.get('/gm', follow_redirects=True)
    assert response.status_code == 200
    # Should redirect to login page
    assert response.request.path == '/gm/login' or 'login' in response.get_data(as_text=True).lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
