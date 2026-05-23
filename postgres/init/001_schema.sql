CREATE TABLE IF NOT EXISTS wiki_pages (
    page_id            BIGINT PRIMARY KEY,
    title              TEXT NOT NULL,
    revision_id        BIGINT,
    revision_timestamp TIMESTAMP,
    raw_wikitext       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wiki_page_features (
    page_id                    BIGINT PRIMARY KEY REFERENCES wiki_pages(page_id),

    wikitext_length_bytes      INT NOT NULL,
    template_count             INT NOT NULL,
    image_count                INT NOT NULL,
    reference_count            INT NOT NULL,
    heading_count              INT NOT NULL,
    internal_link_count        INT NOT NULL,
    external_link_count        INT NOT NULL,
    category_count             INT NOT NULL,

    table_tag_count            INT,
    paragraph_tag_count        INT,
    rendered_html_length_bytes INT,
    render_expansion_ratio     FLOAT,
    html_tag_count             INT
);

CREATE TABLE IF NOT EXISTS wiki_page_labels (
    page_id            BIGINT PRIMARY KEY REFERENCES wiki_pages(page_id),
    avg_response_time  FLOAT,
    is_slow            SMALLINT CHECK (is_slow IN (0, 1))
);

CREATE TABLE IF NOT EXISTS wiki_page_predictions (
    page_id BIGINT PRIMARY KEY REFERENCES wiki_pages(page_id),
    predicted_slow SMALLINT CHECK (predicted_slow IN (0, 1)),
    model_name TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wiki_pages_title
ON wiki_pages(title);

CREATE INDEX IF NOT EXISTS idx_wiki_page_labels_is_slow
ON wiki_page_labels(is_slow);

CREATE INDEX IF NOT EXISTS idx_wiki_page_predictions_predicted_slow
ON wiki_page_predictions(predicted_slow);
