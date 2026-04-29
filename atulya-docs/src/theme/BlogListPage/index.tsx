import React, {useEffect, useState} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import type {Props} from '@theme/BlogListPage';
import type {PropBlogPostContent} from '@docusaurus/plugin-content-blog';
import styles from './styles.module.css';

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
}

/** Each phrase: text shown after "atulya.", its color, and an optional reply line. */
const PHRASES: {text: string; color: string; reply: string}[] = [
  {text: 'retain()',         color: '#dc2626', reply: '// memory stored ✓'},
  {text: 'recall()',         color: '#f59e0b', reply: '// 12 relevant facts found'},
  {text: 'reflect()',        color: '#34d399', reply: '// reasoning complete'},
  {text: 'says("hello 👋")', color: '#60a5fa', reply: '// context: you were here before'},
  {text: 'isAlive()',        color: '#a78bfa', reply: '// true — memory persists'},
  {text: 'cortex.sync()',    color: '#f472b6', reply: '// context beats cortex ✓'},
  {text: 'dream()',          color: '#fbbf24', reply: '// synthesising overnight…'},
  {text: 'brain.check()',    color: '#34d399', reply: '// integrity: nominal'},
];

/**
 * Animated terminal placeholder for blog cards with no cover image.
 * Cycles through Atulya API ops + easter-egg phrases with a typing effect.
 */
function BlogImagePlaceholder(): React.JSX.Element {
  const [idx, setIdx]         = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const cycle = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setIdx(i => (i + 1) % PHRASES.length);
        setVisible(true);
      }, 350);
    }, 2800);
    return () => clearInterval(cycle);
  }, []);

  const {text, color, reply} = PHRASES[idx];

  return (
    <svg
      viewBox="0 0 400 220"
      xmlns="http://www.w3.org/2000/svg"
      className={styles.cardImageSvg}
      aria-hidden="true"
    >
      <defs>
        <pattern id="bp-grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#1e1e1e" strokeWidth="0.5" />
        </pattern>
        <style>{`
          @keyframes bp-fadein { from{opacity:0;transform:translateY(5px)} to{opacity:1;transform:translateY(0)} }
          @keyframes bp-pulse  { 0%,100%{opacity:0.15} 50%{opacity:0.45} }
          .bp-phrase { animation: bp-fadein 0.35s ease-out both; }
          .bp-reply  { animation: bp-fadein 0.35s 0.25s ease-out both; }
          .bp-dot    { animation: bp-pulse var(--dur,2s) ease-in-out infinite; }
          .bp-line   { animation: bp-fadein 0.4s ease-out both; }
        `}</style>
      </defs>

      {/* Background */}
      <rect width="400" height="220" fill="#0d0d0d" />
      <rect width="400" height="220" fill="url(#bp-grid)" />

      {/* Pulsing memory-node dots */}
      {([
        [40,22,2.2,'2s'],[90,30,1.5,'2.6s'],[155,18,1.8,'1.8s'],
        [220,28,1.4,'3.1s'],[285,20,2,'2.3s'],[345,26,1.6,'1.5s'],[385,16,1.2,'2.8s'],
      ] as [number,number,number,string][]).map(([cx,cy,r,dur], i) => (
        <circle key={i} cx={cx} cy={cy} r={r} fill={color} style={{'--dur': dur} as React.CSSProperties} className="bp-dot" />
      ))}

      {/* Connecting line between dots — subtle */}
      <polyline
        points="40,22 90,30 155,18 220,28 285,20 345,26 385,16"
        fill="none" stroke={color} strokeWidth="0.4" opacity="0.2"
      />

      {/* Top-left window chrome */}
      <circle cx="22" cy="52" r="4" fill="#333" />
      <circle cx="34" cy="52" r="4" fill="#333" />
      <circle cx="46" cy="52" r="4" fill="#333" />
      <rect x="14" y="44" width="372" height="1" fill="#1e1e1e" />

      {/* Prompt prefix — static */}
      <text x="22" y="88" fontFamily="'JetBrains Mono',monospace" fontSize="13" fill="#3c3c3c">~/</text>
      <text x="42" y="88" fontFamily="'JetBrains Mono',monospace" fontSize="13" fill="#555">$</text>
      <text x="56" y="88" fontFamily="'JetBrains Mono',monospace" fontSize="13" fill="#666">atulya.</text>

      {/* Cycling phrase */}
      {visible && (
        <text
          key={idx}
          className="bp-phrase"
          x="117"
          y="88"
          fontFamily="'JetBrains Mono',monospace"
          fontSize="13"
          fill={color}
          fontWeight="bold"
        >
          {text}
        </text>
      )}

      {/* Blinking cursor removed — fade-in animation signals transition */}

      {/* Reply line */}
      {visible && (
        <text
          key={`r${idx}`}
          className="bp-reply"
          x="22"
          y="112"
          fontFamily="'JetBrains Mono',monospace"
          fontSize="11"
          fill="#3a3a3a"
        >
          {reply}
        </text>
      )}

      {/* Ghost output skeleton lines */}
      <rect className="bp-line" x="22" y="128" width="160" height="2.5" rx="1.2" fill="#1a1a1a" />
      <rect className="bp-line" x="22" y="138" width="110" height="2.5" rx="1.2" fill="#1a1a1a" style={{animationDelay:'0.1s'}} />
      <rect className="bp-line" x="22" y="148" width="75"  height="2.5" rx="1.2" fill="#1a1a1a" style={{animationDelay:'0.2s'}} />

      {/* Bottom bar */}
      <rect x="0" y="205" width="400" height="15" fill="#0a0a0a" />
      <text x="200" y="215" fontFamily="'Space Grotesk',sans-serif" fontSize="8" fill="#2a2a2a" textAnchor="middle" letterSpacing="3">ATULYA · PERSISTENT MEMORY</text>
    </svg>
  );
}

function BlogCard({content}: {content: PropBlogPostContent}) {
  const {metadata, assets} = content;
  const {title, description, date, readingTime, permalink, frontMatter} = metadata;
  const rawImage = assets.image ?? frontMatter.image;

  return (
    <Link to={permalink} className={styles.card}>
      <div className={styles.cardImageWrapper}>
        {rawImage ? (
          <img src={rawImage} alt={title} className={styles.cardImage} />
        ) : (
          <BlogImagePlaceholder />
        )}
      </div>
      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{title}</h2>
        {description && <p className={styles.cardDescription}>{description}</p>}
        <div className={styles.cardFooter}>
          <span className={styles.cardDate}>{formatDate(date)}</span>
          {readingTime !== undefined && (
            <span className={styles.cardReadTime}>{Math.ceil(readingTime)} min read</span>
          )}
        </div>
      </div>
    </Link>
  );
}

export default function BlogListPage({items, metadata}: Props): React.ReactElement {
  const {blogTitle, blogDescription, totalPages, page, nextPage, previousPage} = metadata;

  return (
    <Layout title={blogTitle} description={blogDescription}>
      <main className={styles.blogPage}>
        <header className={styles.header}>
          <p className={styles.headerEyebrow}>memory that thinks out loud</p>
          <h1 className={styles.headerTitle}>Atulya writes its own story</h1>
          <p className={styles.headerSubtitle}>
            Every post is a retained observation — agents, memory, and the ideas that keep compounding.
          </p>
        </header>

        <div className={styles.grid}>
          {items.map(({content: BlogPostContent}) => (
            <BlogCard key={BlogPostContent.metadata.permalink} content={BlogPostContent} />
          ))}
        </div>

        {totalPages > 1 && (
          <nav className={styles.pagination}>
            {previousPage && (
              <Link to={previousPage} className={styles.paginationButton}>
                ← Previous
              </Link>
            )}
            <span className={styles.paginationInfo}>
              Page {page} of {totalPages}
            </span>
            {nextPage && (
              <Link to={nextPage} className={styles.paginationButton}>
                Next →
              </Link>
            )}
          </nav>
        )}
      </main>
    </Layout>
  );
}
