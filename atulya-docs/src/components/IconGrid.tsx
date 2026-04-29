/**
 *
 * IconGrid — auto-fill grid of icon+label cards.
 * Each item can link to a doc page. Supports react-icons IconType or imgSrc.
 *
 * Usage:
 *   import {IconGrid} from '@site/src/components/IconGrid';
 *   <IconGrid items={[{label: 'Python', icon: SiPython, href: '/sdks/python'}]} />
 */
import React from 'react';
import type {IconType} from 'react-icons';
import styles from './IconGrid.module.css';

export interface IconGridItem {
  label: string;
  href?: string;
  icon?: IconType;
  imgSrc?: string;
}

export function IconGrid({items}: {items: IconGridItem[]}): React.JSX.Element {
  return (
    <div className={styles.grid}>
      {items.map(({label, href, icon: Icon, imgSrc}) => {
        const card = (
          <div className={`${styles.card} ${href ? styles.cardLink : ''}`}>
            <div className={styles.icon}>
              {Icon && <Icon size={26} />}
              {imgSrc && (
                <img src={imgSrc} alt={label} style={{width: 26, height: 26, objectFit: 'contain'}} />
              )}
            </div>
            <span
              className={styles.label}
              // Override Docusaurus gradient link text-fill on parent <a>
              style={{color: 'var(--ifm-font-color-base)', WebkitTextFillColor: 'var(--ifm-font-color-base)'}}
            >
              {label}
            </span>
          </div>
        );
        return href
          ? <a key={label} href={href} className={styles.anchor}>{card}</a>
          : <div key={label}>{card}</div>;
      })}
    </div>
  );
}
