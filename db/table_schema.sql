CREATE TABLE IF NOT EXISTS locations (
    id SERIAL PRIMARY KEY,
    region VARCHAR(50),
    district VARCHAR(50),
    municipality VARCHAR(50),
    UNIQUE(region, district, municipality)
);

CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    location_id INTEGER REFERENCES locations(id),
    source VARCHAR(255) NOT NULL,
    url TEXT NOT NULL unique,
    year INTEGER,
    date DATE,
    author VARCHAR(100),
    title TEXT NOT NULL,
    description TEXT,
    content TEXT NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('czech', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('czech', coalesce(description, '')), 'B') ||
        setweight(to_tsvector('czech', coalesce(content, '')), 'C')
    ) STORED,
    db_inserted_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS article_html (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    html_base64 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keywords (
    id SERIAL PRIMARY KEY,
    keyword VARCHAR(16) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS article_keywords (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS article_files (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_type VARCHAR(20) NOT NULL CHECK (file_type IN ('image', 'video', 'document')),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_articles_location_id ON articles(location_id);
CREATE INDEX idx_article_keyword_id ON article_keywords(keyword_id);
CREATE INDEX idx_articles_search_vector ON articles USING GIN(search_vector);