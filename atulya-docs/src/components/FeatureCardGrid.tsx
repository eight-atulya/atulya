import React from 'react';
import useBaseUrl from '@docusaurus/useBaseUrl';
import styles from './FeatureCardGrid.module.css';

export interface FeatureCardItem {
  icon: string;
  title: string;
  description: string;
  eyebrow?: string;
}

interface FeatureCardGridProps {
  cards: FeatureCardItem[];
}

export default function FeatureCardGrid({cards}: FeatureCardGridProps): React.JSX.Element {
  return (
    <div className={styles.grid}>
      {cards.map((card) => {
        const iconSrc = useBaseUrl(card.icon);
        return (
          <div key={card.title} className={styles.card}>
            <div className={styles.iconWrap}>
              <img src={iconSrc} alt="" className={styles.icon} />
            </div>
            {card.eyebrow && <div className={styles.eyebrow}>{card.eyebrow}</div>}
            <h3 className={styles.title}>{card.title}</h3>
            <p className={styles.description}>{card.description}</p>
          </div>
        );
      })}
    </div>
  );
}
