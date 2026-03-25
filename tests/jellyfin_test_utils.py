from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.jellyfin import JELLYFIN_EPISODE_TYPE, JELLYFIN_MOVIE_TYPE, JELLYFIN_SERIES_TYPE


def create_jellyfin_test_db(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE Users (
            Id TEXT PRIMARY KEY,
            Username TEXT NOT NULL
        );

        CREATE TABLE BaseItems (
            Id TEXT PRIMARY KEY,
            Name TEXT NOT NULL,
            CleanName TEXT,
            ProductionYear INTEGER,
            ParentIndexNumber INTEGER,
            IndexNumber INTEGER,
            SeriesId TEXT,
            Type TEXT NOT NULL
        );

        CREATE TABLE BaseItemProviders (
            ItemId TEXT NOT NULL,
            ProviderId TEXT NOT NULL,
            ProviderValue TEXT NOT NULL
        );

        CREATE TABLE UserData (
            ItemId TEXT NOT NULL,
            UserId TEXT NOT NULL,
            CustomDataKey TEXT,
            Played INTEGER DEFAULT 0,
            PlayCount INTEGER DEFAULT 0,
            PlaybackPositionTicks INTEGER DEFAULT 0,
            LastPlayedDate TEXT
        );
        """
    )
    connection.commit()
    connection.close()
    return path


def add_jellyfin_user(path: Path, *, user_id: str, username: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO Users (Id, Username) VALUES (?, ?)",
        (user_id, username),
    )
    connection.commit()
    connection.close()


def add_jellyfin_series(
    path: Path,
    *,
    series_id: str,
    title: str,
    clean_name: str | None = None,
    production_year: int | None = None,
    imdb_id: str | None = None,
) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO BaseItems (
            Id,
            Name,
            CleanName,
            ProductionYear,
            ParentIndexNumber,
            IndexNumber,
            SeriesId,
            Type
        ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?)
        """,
        (
            series_id,
            title,
            clean_name or title,
            production_year,
            JELLYFIN_SERIES_TYPE,
        ),
    )
    if imdb_id:
        connection.execute(
            """
            INSERT INTO BaseItemProviders (ItemId, ProviderId, ProviderValue)
            VALUES (?, 'Imdb', ?)
            """,
            (series_id, imdb_id),
        )
    connection.commit()
    connection.close()


def add_jellyfin_episode(
    path: Path,
    *,
    episode_id: str,
    series_id: str,
    title: str,
    season_number: int,
    episode_number: int,
    imdb_id: str | None = None,
    tvdb_id: str | None = None,
) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO BaseItems (
            Id,
            Name,
            CleanName,
            ProductionYear,
            ParentIndexNumber,
            IndexNumber,
            SeriesId,
            Type
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            episode_id,
            title,
            title,
            season_number,
            episode_number,
            series_id,
            JELLYFIN_EPISODE_TYPE,
        ),
    )
    if imdb_id:
        connection.execute(
            """
            INSERT INTO BaseItemProviders (ItemId, ProviderId, ProviderValue)
            VALUES (?, 'Imdb', ?)
            """,
            (episode_id, imdb_id),
        )
    if tvdb_id:
        connection.execute(
            """
            INSERT INTO BaseItemProviders (ItemId, ProviderId, ProviderValue)
            VALUES (?, 'Tvdb', ?)
            """,
            (episode_id, tvdb_id),
        )
    connection.commit()
    connection.close()


def add_jellyfin_movie(
    path: Path,
    *,
    movie_id: str,
    title: str,
    clean_name: str | None = None,
    production_year: int | None = None,
    imdb_id: str | None = None,
) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO BaseItems (
            Id,
            Name,
            CleanName,
            ProductionYear,
            ParentIndexNumber,
            IndexNumber,
            SeriesId,
            Type
        ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?)
        """,
        (
            movie_id,
            title,
            clean_name or title,
            production_year,
            JELLYFIN_MOVIE_TYPE,
        ),
    )
    if imdb_id:
        connection.execute(
            """
            INSERT INTO BaseItemProviders (ItemId, ProviderId, ProviderValue)
            VALUES (?, 'Imdb', ?)
            """,
            (movie_id, imdb_id),
        )
    connection.commit()
    connection.close()


def add_jellyfin_userdata(
    path: Path,
    *,
    item_id: str,
    user_id: str,
    custom_data_key: str | None,
    played: int = 0,
    play_count: int = 0,
    playback_position_ticks: int = 0,
    last_played_date: str | None = None,
) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO UserData (
            ItemId,
            UserId,
            CustomDataKey,
            Played,
            PlayCount,
            PlaybackPositionTicks,
            LastPlayedDate
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            user_id,
            custom_data_key,
            played,
            play_count,
            playback_position_ticks,
            last_played_date,
        ),
    )
    connection.commit()
    connection.close()
