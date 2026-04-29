/**
 *
 * PageHero — full-bleed section header with Atulya red gradient title.
 * Breaks out of Docusaurus's content max-width to span the full viewport.
 *
 * Usage in MDX:
 *   import PageHero from '@site/src/components/PageHero';
 *   <PageHero title="API Reference" subtitle="Complete REST API documentation." />
 */
import React, {type ReactNode} from 'react';
import styles from './PageHero.module.css';

interface PageHeroProps {
  title: string;
  subtitle?: string;
}

export default function PageHero({title, subtitle}: PageHeroProps): ReactNode {
  return (
    <div className={styles.hero}>
      <h1 className={styles.title}>{title}</h1>
      {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
    </div>
  );
}
