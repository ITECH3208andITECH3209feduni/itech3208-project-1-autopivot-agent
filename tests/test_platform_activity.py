"""APA-232 integration checks against two dealerships and actual stored files."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from test_platform_administration import auth, environment  # shared isolated DB fixture
from database.models import AuditLog, Image, ProcessingJob, VehicleListing


@pytest.fixture()
def activity_environment(environment):
    client, sessions, users, root = environment
    with sessions() as session:
        for dealership_id, email in [(1, 'admin@firstmotors.com.au'), (2, 'admin@secondmotors.com.au')]:
            listing = VehicleListing(dealership_id=dealership_id, created_by_user_id=users[email],
                title='PRIVATE_TITLE', make='Holden', model='Commodore', year=2014,
                description='PRIVATE_DESCRIPTION')
            session.add(listing)
            session.flush()
            original = Image(vehicle_listing_id=listing.id, image_type='original',
                original_filename='PRIVATE_FILENAME.jpg', storage_path=f'{dealership_id}/original.jpg',
                mime_type='image/jpeg', file_size_bytes=123, width=10, height=10)
            processed = Image(vehicle_listing_id=listing.id, image_type='processed',
                original_filename='PRIVATE_OUTPUT.jpg', storage_path=f'{dealership_id}/processed.jpg',
                mime_type='image/jpeg', file_size_bytes=123, width=10, height=10)
            session.add_all([original, processed])
            session.flush()
            for state in (['pending', 'processing', 'completed', 'failed'] if dealership_id == 1 else ['completed']):
                session.add(ProcessingJob(vehicle_listing_id=listing.id, dealership_id=dealership_id,
                    input_image_id=original.id, output_image_id=processed.id if state == 'completed' else None,
                    processing_type='full_pipeline', status=state, error_message='PRIVATE_ERROR /secret/photo.jpg',
                    model_used='PRIVATE_MODEL', created_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
            folder = root / str(dealership_id)
            folder.mkdir(parents=True)
            for filename in ['original.jpg', 'processed.jpg', 'backdrop.jpg', 'overlay.jpg']:
                (folder / filename).write_bytes(b'PRIVATE_PHOTO_BYTES')
        session.commit()
    return environment


def platform(users):
    return auth(users['platform@autopivot.com.au'], 'platform@autopivot.com.au', 'platform_admin')


def test_summary_counts_are_scoped_and_only_original_uploads_count(activity_environment):
    client, sessions, users, _ = activity_environment
    first = client.get('/api/platform/dealerships/1/activity', headers=platform(users))
    assert first.status_code == 200
    body = first.json()
    assert body == {
        'dealership_id': 1, 'active_users': 2, 'vehicle_count': 1,
        'original_image_count': 1, 'job_count': 4,
        'jobs_by_status': {'pending': 1, 'processing': 1, 'completed': 1, 'failed': 1},
        'latest_job_at': '2026-10-01T00:00:00Z',
    }
    second = client.get('/api/platform/dealerships/2/activity', headers=platform(users)).json()
    assert second['job_count'] == 1
    assert second['active_users'] == 1
    with sessions() as session:
        records = session.scalars(select(AuditLog).where(AuditLog.action == 'dealership_activity_viewed')).all()
        assert len(records) == 2
        assert all(record.outcome == 'success' for record in records)


def test_job_allowlist_scope_filter_and_stable_pagination(activity_environment):
    client, _, users, _ = activity_environment
    headers = platform(users)
    url = '/api/platform/dealerships/1/jobs'
    first = client.get(url + '?limit=2', headers=headers).json()
    second = client.get(url + '?limit=2&offset=2', headers=headers).json()
    assert first['total'] == second['total'] == 4
    assert [j['id'] for j in first['items'] + second['items']] == [4, 3, 2, 1]
    for job in first['items'] + second['items']:
        assert set(job) == {'id', 'vehicle_listing_id', 'processing_type', 'status', 'review_state',
                            'created_at', 'started_at', 'completed_at'}
        assert job['vehicle_listing_id'] == 1
    assert 'PRIVATE' not in str(first) + str(second)
    filtered = client.get(url + '?status=failed', headers=headers).json()
    assert filtered['total'] == 1
    assert filtered['items'][0]['status'] == 'failed'
    assert client.get(url + '?offset=100', headers=headers).json()['items'] == []


@pytest.mark.parametrize('suffix', ['activity', 'jobs'])
@pytest.mark.parametrize('email,role', [
    ('admin@firstmotors.com.au', 'dealership_admin'),
    ('admin@secondmotors.com.au', 'dealership_admin'),
    ('staff@firstmotors.com.au', 'dealership_staff'),
])
def test_dealership_roles_denied_on_own_and_other_dealership(environment, suffix, email, role):
    client, sessions, users, _ = environment
    for dealership_id in [1, 2]:
        url = f'/api/platform/dealerships/{dealership_id}/{suffix}'
        assert client.get(url, headers=auth(users[email], email, role, 1)).status_code == 403
        with sessions() as session:
            assert session.scalar(select(AuditLog).where(AuditLog.request_path == url, AuditLog.outcome == 'denied'))


@pytest.mark.parametrize('suffix', ['activity', 'jobs'])
def test_missing_auth_missing_dealership_and_password_change(environment, suffix):
    client, sessions, users, _ = environment
    url = f'/api/platform/dealerships/1/{suffix}'
    assert client.get(url).status_code == 401
    assert client.get(f'/api/platform/dealerships/999/{suffix}', headers=platform(users)).status_code == 404
    from database.models import User
    with sessions() as session:
        session.get(User, users['platform@autopivot.com.au']).must_change_password = True
        session.commit()
    assert client.get(url, headers=platform(users)).status_code == 403


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'offset=-1', 'status=unknown'])
def test_invalid_job_queries(environment, query):
    client, _, users, _ = environment
    assert client.get('/api/platform/dealerships/1/jobs?' + query, headers=platform(users)).status_code == 422


def test_empty_dealership_has_zero_counts_and_empty_page(environment):
    client, _, users, _ = environment
    body = client.get('/api/platform/dealerships/1/activity', headers=platform(users)).json()
    assert body['job_count'] == body['vehicle_count'] == body['original_image_count'] == 0
    assert body['latest_job_at'] is None
    assert all(value == 0 for value in body['jobs_by_status'].values())
    assert client.get('/api/platform/dealerships/1/jobs', headers=platform(users)).json()['items'] == []


@pytest.mark.parametrize('dealership_id', [1, 2])
@pytest.mark.parametrize('filename', ['original.jpg', 'processed.jpg', 'backdrop.jpg', 'overlay.jpg', 'missing.jpg'])
def test_platform_photo_access_denied_and_logged(activity_environment, dealership_id, filename):
    client, sessions, users, _ = activity_environment
    response = client.get(f'/api/files/{dealership_id}/{filename}', headers=platform(users))
    assert response.status_code == 404
    assert 'PRIVATE_PHOTO_BYTES' not in response.text
    with sessions() as session:
        record = session.scalar(select(AuditLog).where(AuditLog.action == 'platform_photo_access'))
        assert record.outcome == 'denied'
        assert record.actor_user_id == users['platform@autopivot.com.au']
        assert filename not in record.request_path


def test_dealership_can_still_read_own_files_but_not_other_files(activity_environment):
    client, _, users, _ = activity_environment
    headers = auth(users['admin@firstmotors.com.au'], 'admin@firstmotors.com.au', 'dealership_admin', 1)
    assert client.get('/api/files/1/original.jpg', headers=headers).content == b'PRIVATE_PHOTO_BYTES'
    assert client.get('/api/files/2/original.jpg', headers=headers).status_code == 404
    assert client.get('/api/files/1/original.jpg').status_code == 401


@pytest.mark.parametrize('suffix,expected', [('', 403), ('/1', 403), ('/1/jobs', 403), ('/1/images', 405)])
def test_existing_listing_routes_do_not_bypass_platform_restriction(activity_environment, suffix, expected):
    client, _, users, _ = activity_environment
    # There is no GET image-list endpoint: listing detail supplies images to
    # dealership users. The unsupported method must not return photographs.
    assert client.get('/api/listings' + suffix, headers=platform(users)).status_code == expected
