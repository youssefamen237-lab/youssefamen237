import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import time

logger = logging.getLogger(__name__)

# Lazy imports - only import when needed to avoid failures if packages not installed
def _lazy_import_google():
    try:
        import google.auth.transport.requests
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload, HttpError
        return {
            'google_auth': google.auth.transport.requests,
            'Credentials': Credentials,
            'Request': Request,
            'build': build,
            'MediaFileUpload': MediaFileUpload,
            'HttpError': HttpError
        }
    except ImportError as e:
        logger.error(f"Google API libraries not installed: {e}")
        raise

# Import on module load
try:
    _google_imports = _lazy_import_google()
except ImportError:
    _google_imports = None

class YouTubeManager:
    def __init__(self):
        self.client_id = os.getenv('YT_CLIENT_ID_3')
        self.client_secret = os.getenv('YT_CLIENT_SECRET_3')
        self.refresh_token = os.getenv('YT_REFRESH_TOKEN_3')
        self.channel_id = os.getenv('YT_CHANNEL_ID')
        self.youtube = None
        
        # Check if credentials are available
        if not all([self.client_id, self.client_secret, self.refresh_token, self.channel_id]):
            logger.warning(
                "⚠️  YouTube API credentials incomplete. "
                "Please set: YT_CLIENT_ID_3, YT_CLIENT_SECRET_3, YT_REFRESH_TOKEN_3, YT_CHANNEL_ID"
            )
            return
        
        self.authenticate()

    def authenticate(self) -> bool:
        try:
            if not _google_imports:
                logger.error("Google API libraries not available")
                return False
            
            Credentials = _google_imports['Credentials']
            Request = _google_imports['Request']
            build = _google_imports['build']
            
            creds = Credentials(
                token=None,
                refresh_token=self.refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=['https://www.googleapis.com/auth/youtube']
            )
            
            request = Request()
            creds.refresh(request)
            
            self.youtube = build('youtube', 'v3', credentials=creds)
            logger.info("YouTube authentication successful")
            return True
        except Exception as e:
            logger.error(f"YouTube authentication failed: {e}")
            return False

    def upload_short(self, video_path: str, title: str, description: str,
                    tags: List[str] = None, made_for_kids: bool = False) -> Optional[str]:
        try:
            logger.info(f"🎬 Uploading video: {video_path}")
            
            if not _google_imports:
                logger.error("❌ Google API libraries not available")
                return None
            
            MediaFileUpload = _google_imports['MediaFileUpload']
            HttpError = _google_imports.get('HttpError')
            
            if not self.youtube:
                logger.warning("⚠️  YouTube not authenticated, attempting authentication...")
                if not self.authenticate():
                    logger.error("❌ Authentication failed")
                    return None

            if tags is None:
                tags = ["shorts", "quiz", "brain"]

            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'tags': tags,
                    'categoryId': '24',
                    'defaultLanguage': 'en'
                },
                'status': {
                    'privacyStatus': 'public',
                    'madeForKids': made_for_kids,
                    'selfDeclaredMadeForKids': made_for_kids
                }
            }

            logger.info(f"   Title: {title[:50]}...")
            logger.info(f"   Description: {description[:50]}...")
            logger.info(f"   Tags: {', '.join(tags)}")
            
            # Check if file exists and get size
            if not os.path.exists(video_path):
                logger.error(f"❌ Video file not found: {video_path}")
                return None
            
            file_size = os.path.getsize(video_path)
            logger.info(f"   File size: {file_size / (1024*1024):.2f} MB")
            
            media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
            
            request = self.youtube.videos().insert(
                part='snippet,status',
                body=body,
                media_body=media
            )

            response = None
            max_retries = 5
            retry_count = 0
            chunk_count = 0
            
            logger.info("   Starting upload chunks...")
            while response is None and retry_count < max_retries:
                try:
                    status, response = request.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        logger.info(f"   Upload progress: {progress}%")
                        chunk_count += 1
                    
                    if response:
                        logger.info("   Upload complete!")
                        break
                        
                except Exception as e:
                    if HttpError and isinstance(e, HttpError):
                        if hasattr(e, 'resp') and e.resp.status in [500, 502, 503, 504]:
                            # Retryable errors
                            retry_count += 1
                            logger.warning(f"   ⚠️  Server error ({e.resp.status}), retry {retry_count}/{max_retries}...")
                            time.sleep(5 * retry_count)
                        else:
                            logger.error(f"   ❌ YouTube API error: {e}")
                            return None
                    else:
                        retry_count += 1
                        logger.warning(f"   ⚠️  Chunk error: {e}, retry {retry_count}/{max_retries}...")
                        time.sleep(5)
            
            if response is None:
                logger.error(f"❌ Upload failed after {max_retries} retries")
                return None
            
            if 'id' not in response:
                logger.error(f"❌ Upload response missing video ID: {response}")
                return None
            
            video_id = response['id']
            logger.info(f"✅ Video uploaded successfully!")
            logger.info(f"   Video ID: {video_id}")
            logger.info(f"   URL: https://www.youtube.com/shorts/{video_id}")
            return video_id

        except Exception as e:
            logger.error(f"❌ Error uploading video: {e}", exc_info=True)
            return None

    def get_video_analytics(self, video_id: str) -> Optional[Dict[str, Any]]:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return None

            # Get basic video stats
            request = self.youtube.videos().list(
                part='statistics,contentDetails,snippet',
                id=video_id
            )
            response = request.execute()

            if not response.get('items'):
                return None

            item = response['items'][0]
            stats = item.get('statistics', {})
            snippet = item.get('snippet', {})
            content = item.get('contentDetails', {})

            analytics = {
                'video_id': video_id,
                'title': snippet.get('title', ''),
                'view_count': int(stats.get('viewCount', 0)),
                'like_count': int(stats.get('likeCount', 0)),
                'comment_count': int(stats.get('commentCount', 0)),
                'favorite_count': int(stats.get('favoriteCount', 0)),
                'duration': content.get('duration', ''),
                'published_at': snippet.get('publishedAt', ''),
                'description': snippet.get('description', '')
            }

            # Calculate estimated metrics
            analytics['estimated_ctr'] = self._estimate_ctr(analytics)
            analytics['estimated_completion'] = self._estimate_completion(analytics)
            analytics['estimated_watch_time'] = self._estimate_watch_time(analytics)

            return analytics

        except Exception as e:
            logger.error(f"Error getting video analytics: {e}")
            return None

    def _estimate_ctr(self, analytics: Dict) -> float:
        # Rough estimation based on engagement
        views = analytics.get('view_count', 0)
        clicks = analytics.get('like_count', 0) + analytics.get('comment_count', 0) * 2
        if views == 0:
            return 0
        return min((clicks / views) * 100, 100)

    def _estimate_completion(self, analytics: Dict) -> float:
        # Rough estimation based on comments and likes
        views = analytics.get('view_count', 0)
        engagement = analytics.get('like_count', 0) + analytics.get('comment_count', 0)
        if views == 0:
            return 0
        return min((engagement / views) * 50 + 20, 100)

    def _estimate_watch_time(self, analytics: Dict) -> float:
        # Rough estimation of average watch time
        views = analytics.get('view_count', 0)
        if views == 0:
            return 0
        engagement_rate = self._estimate_ctr(analytics)
        return (engagement_rate / 100) * 30

    def wait_until_public(self, video_id: str, timeout: int = 180, interval: int = 5) -> bool:
        """Poll YouTube API until the video's privacy status is 'public' or timeout."""
        try:
            if not self.youtube:
                if not self.authenticate():
                    return False

            elapsed = 0
            while elapsed < timeout:
                request = self.youtube.videos().list(part='status', id=video_id)
                resp = request.execute()
                items = resp.get('items', [])
                if not items:
                    time.sleep(interval)
                    elapsed += interval
                    continue

                status = items[0].get('status', {})
                privacy = status.get('privacyStatus')
                upload_state = status.get('uploadStatus') or status.get('processingDetails', {}).get('processingStatus')

                if privacy == 'public':
                    return True

                # If explicitly private or failed, stop early
                if privacy in ('private', 'rejected'):
                    return False

                time.sleep(interval)
                elapsed += interval

            return False

        except Exception as e:
            logger.error(f"Error while waiting for video to become public: {e}")
            return False

    def get_channel_analytics(self) -> Optional[Dict[str, Any]]:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return None

            request = self.youtube.channels().list(
                part='statistics,snippet,contentDetails',
                forUsername='@' + self.channel_id if not self.channel_id.startswith('UC') else None,
                id=self.channel_id if self.channel_id.startswith('UC') else None
            )
            response = request.execute()

            if not response.get('items'):
                return None

            item = response['items'][0]
            stats = item.get('statistics', {})
            snippet = item.get('snippet', {})

            analytics = {
                'channel_id': item['id'],
                'channel_title': snippet.get('title', ''),
                'subscriber_count': int(stats.get('subscriberCount', 0)),
                'view_count': int(stats.get('viewCount', 0)),
                'video_count': int(stats.get('videoCount', 0)),
                'description': snippet.get('description', ''),
                'published_at': snippet.get('publishedAt', '')
            }

            return analytics

        except Exception as e:
            logger.error(f"Error getting channel analytics: {e}")
            return None

    def get_recent_videos(self, max_results: int = 50) -> List[Dict[str, Any]]:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return []

            # Get uploads playlist
            channels = self.youtube.channels().list(
                part='contentDetails',
                id=self.channel_id
            ).execute()

            if not channels.get('items'):
                return []

            uploads_playlist = channels['items'][0]['contentDetails']['relatedPlaylists']['uploads']

            # Get videos from uploads playlist
            videos = []
            request = self.youtube.playlistItems().list(
                part='snippet,contentDetails',
                playlistId=uploads_playlist,
                maxResults=min(max_results, 50)
            )

            while request:
                response = request.execute()
                for item in response.get('items', []):
                    video_id = item['contentDetails']['videoId']
                    videos.append({
                        'video_id': video_id,
                        'title': item['snippet']['title'],
                        'published_at': item['snippet']['publishedAt'],
                        'description': item['snippet']['description']
                    })

                request = self.youtube.playlistItems().list_next(request, response)

            return videos[:max_results]

        except Exception as e:
            logger.error(f"Error getting recent videos: {e}")
            return []

    def create_playlist(self, title: str, description: str = "") -> Optional[str]:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return None

            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'defaultLanguage': 'en'
                },
                'status': {
                    'privacyStatus': 'public'
                }
            }

            request = self.youtube.playlists().insert(
                part='snippet,status',
                body=body
            )
            response = request.execute()

            playlist_id = response['id']
            logger.info(f"Playlist created: {playlist_id}")
            return playlist_id

        except Exception as e:
            logger.error(f"Error creating playlist: {e}")
            return None

    def add_to_playlist(self, playlist_id: str, video_id: str, position: int = 0) -> bool:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return False

            body = {
                'snippet': {
                    'playlistId': playlist_id,
                    'resourceId': {
                        'kind': 'youtube#video',
                        'videoId': video_id
                    },
                    'position': position
                }
            }

            self.youtube.playlistItems().insert(
                part='snippet',
                body=body
            ).execute()

            logger.info(f"Video {video_id} added to playlist {playlist_id}")
            return True

        except Exception as e:
            logger.error(f"Error adding to playlist: {e}")
            return False

    def reply_to_comment(self, comment_id: str, reply_text: str) -> Optional[str]:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return None

            body = {
                'snippet': {
                    'parentId': comment_id,
                    'textOriginal': reply_text
                }
            }

            request = self.youtube.comments().insert(
                part='snippet',
                body=body
            )
            response = request.execute()

            reply_id = response['id']
            logger.info(f"Reply created: {reply_id}")
            return reply_id

        except Exception as e:
            logger.error(f"Error replying to comment: {e}")
            return None

    def get_comments(self, video_id: str, max_results: int = 20) -> List[Dict[str, Any]]:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return []

            request = self.youtube.commentThreads().list(
                part='snippet',
                videoId=video_id,
                textFormat='plainText',
                maxResults=min(max_results, 20),
                order='relevance'
            )

            comments = []
            response = request.execute()

            for item in response.get('items', []):
                comment = item['snippet']['topLevelComment']['snippet']
                comments.append({
                    'comment_id': item['snippet']['topLevelComment']['id'],
                    'author': comment['authorDisplayName'],
                    'text': comment['textDisplay'],
                    'likes': comment['likeCount'],
                    'reply_count': item['snippet']['replyCount'],
                    'published_at': comment['publishedAt']
                })

            return comments

        except Exception as e:
            logger.error(f"Error getting comments: {e}")
            return []

    def update_video_description(self, video_id: str, new_description: str) -> bool:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return False

            # Get current video info
            video = self.youtube.videos().list(
                part='snippet',
                id=video_id
            ).execute()

            if not video.get('items'):
                return False

            snippet = video['items'][0]['snippet']
            snippet['description'] = new_description

            self.youtube.videos().update(
                part='snippet',
                body={'id': video_id, 'snippet': snippet}
            ).execute()

            logger.info(f"Video description updated: {video_id}")
            return True

        except Exception as e:
            logger.error(f"Error updating video description: {e}")
            return False

    def update_video_title(self, video_id: str, new_title: str) -> bool:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return False

            video = self.youtube.videos().list(
                part='snippet',
                id=video_id
            ).execute()

            if not video.get('items'):
                return False

            snippet = video['items'][0]['snippet']
            snippet['title'] = new_title

            self.youtube.videos().update(
                part='snippet',
                body={'id': video_id, 'snippet': snippet}
            ).execute()

            logger.info(f"Video title updated: {video_id}")
            return True

        except Exception as e:
            logger.error(f"Error updating video title: {e}")
            return False

    def get_optimal_upload_time(self, days: int = 7) -> Optional[str]:
        try:
            if not self.youtube:
                if not self.authenticate():
                    return None

            recent_videos = self.get_recent_videos(50)
            if not recent_videos:
                # Default to 5 PM UTC if no videos
                return "17:00:00"

            # Analyze upload times
            upload_hours = {}
            for video in recent_videos[:days * 4]:
                pub_time = datetime.fromisoformat(video['published_at'].replace('Z', '+00:00'))
                hour = pub_time.hour
                upload_hours[hour] = upload_hours.get(hour, 0) + 1

            if upload_hours:
                best_hour = max(upload_hours, key=upload_hours.get)
                return f"{best_hour:02d}:00:00"

            return "17:00:00"

        except Exception as e:
            logger.error(f"Error getting optimal upload time: {e}")
            return None
