/**
 * Shared Utilities Tests
 * @module utils/__tests__/shared-utils
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  formatDate,
  formatTime,
  formatDateTime,
  formatRelativeTime,
  truncate,
  capitalize,
  toTitleCase,
  formatNumber,
  formatCurrency,
  debounce,
  throttle,
  isEmpty,
  isValidEmail,
  SharedUtils
} from '../shared-utils.js';

describe('SharedUtils', () => {
  describe('Date/Time Formatting', () => {
    describe('formatDate', () => {
      it('should format Date object correctly', () => {
        // Use explicit time to avoid timezone issues
        const date = new Date('2024-06-15T12:00:00');
        const result = formatDate(date);
        expect(result).toContain('Jun');
        expect(result).toContain('15');
        expect(result).toContain('2024');
      });

      it('should format date string correctly', () => {
        // Use explicit time to avoid timezone issues
        const result = formatDate('2024-06-15T12:00:00');
        expect(result).toContain('Jun');
        expect(result).toContain('15');
      });

      it('should return empty string for null/undefined', () => {
        expect(formatDate(null)).toBe('');
        expect(formatDate(undefined)).toBe('');
      });

      it('should return empty string for invalid date', () => {
        expect(formatDate('not a date')).toBe('');
      });

      it('should accept custom options', () => {
        const date = new Date('2024-06-15');
        const result = formatDate(date, { month: 'long' });
        expect(result).toContain('June');
      });
    });

    describe('formatTime', () => {
      it('should format time correctly', () => {
        const date = new Date('2024-06-15T14:30:00');
        const result = formatTime(date);
        expect(result).toMatch(/2:30|14:30/);
      });

      it('should return empty string for invalid input', () => {
        expect(formatTime(null)).toBe('');
        expect(formatTime('invalid')).toBe('');
      });
    });

    describe('formatDateTime', () => {
      it('should format date and time correctly', () => {
        const date = new Date('2024-06-15T14:30:00');
        const result = formatDateTime(date);
        expect(result).toContain('Jun');
        expect(result).toContain('15');
      });

      it('should return empty string for invalid input', () => {
        expect(formatDateTime(null)).toBe('');
      });
    });

    describe('formatRelativeTime', () => {
      it('should return "just now" for recent times', () => {
        const now = new Date();
        expect(formatRelativeTime(now)).toBe('just now');
      });

      it('should format minutes ago correctly', () => {
        const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000);
        const result = formatRelativeTime(fiveMinAgo);
        expect(result).toBe('5 minutes ago');
      });

      it('should format single minute correctly', () => {
        const oneMinAgo = new Date(Date.now() - 1 * 60 * 1000);
        const result = formatRelativeTime(oneMinAgo);
        expect(result).toBe('1 minute ago');
      });

      it('should format hours ago correctly', () => {
        const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000);
        const result = formatRelativeTime(twoHoursAgo);
        expect(result).toBe('2 hours ago');
      });

      it('should format days ago correctly', () => {
        const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000);
        const result = formatRelativeTime(threeDaysAgo);
        expect(result).toBe('3 days ago');
      });

      it('should return formatted date for older dates', () => {
        const oldDate = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
        const result = formatRelativeTime(oldDate);
        expect(result).not.toContain('ago');
      });

      it('should return empty string for invalid input', () => {
        expect(formatRelativeTime(null)).toBe('');
        expect(formatRelativeTime('invalid')).toBe('');
      });
    });
  });

  describe('String Utilities', () => {
    describe('truncate', () => {
      it('should truncate long strings', () => {
        const result = truncate('This is a long string that needs truncating', 20);
        expect(result).toBe('This is a long st...');
        expect(result.length).toBe(20);
      });

      it('should not truncate short strings', () => {
        const result = truncate('Short', 20);
        expect(result).toBe('Short');
      });

      it('should handle empty/null input', () => {
        expect(truncate(null)).toBe('');
        expect(truncate(undefined)).toBe('');
        expect(truncate('')).toBe('');
      });

      it('should use default max length of 100', () => {
        const longStr = 'a'.repeat(150);
        const result = truncate(longStr);
        expect(result.length).toBe(100);
      });
    });

    describe('capitalize', () => {
      it('should capitalize first letter', () => {
        expect(capitalize('hello')).toBe('Hello');
        expect(capitalize('HELLO')).toBe('Hello');
      });

      it('should handle empty/null input', () => {
        expect(capitalize(null)).toBe('');
        expect(capitalize('')).toBe('');
      });

      it('should handle single character', () => {
        expect(capitalize('a')).toBe('A');
      });
    });

    describe('toTitleCase', () => {
      it('should convert to title case', () => {
        expect(toTitleCase('hello world')).toBe('Hello World');
        expect(toTitleCase('HELLO WORLD')).toBe('Hello World');
      });

      it('should handle empty/null input', () => {
        expect(toTitleCase(null)).toBe('');
        expect(toTitleCase('')).toBe('');
      });
    });
  });

  describe('Number Utilities', () => {
    describe('formatNumber', () => {
      it('should format with thousands separator', () => {
        expect(formatNumber(1234567)).toBe('1,234,567');
      });

      it('should respect decimal places', () => {
        const result = formatNumber(1234.5678, 2);
        expect(result).toBe('1,234.57');
      });

      it('should handle null/undefined', () => {
        expect(formatNumber(null)).toBe('0');
        expect(formatNumber(undefined)).toBe('0');
      });

      it('should handle NaN', () => {
        expect(formatNumber(NaN)).toBe('0');
      });
    });

    describe('formatCurrency', () => {
      it('should format as USD by default', () => {
        const result = formatCurrency(1234.56);
        expect(result).toBe('$1,234.56');
      });

      it('should handle null/undefined', () => {
        expect(formatCurrency(null)).toBe('$0.00');
        expect(formatCurrency(undefined)).toBe('$0.00');
      });

      it('should format negative amounts', () => {
        const result = formatCurrency(-50);
        expect(result).toContain('50.00');
      });
    });
  });

  describe('DOM Utilities', () => {
    describe('debounce', () => {
      beforeEach(() => {
        vi.useFakeTimers();
      });

      afterEach(() => {
        vi.useRealTimers();
      });

      it('should debounce function calls', () => {
        const fn = vi.fn();
        const debouncedFn = debounce(fn, 100);

        debouncedFn();
        debouncedFn();
        debouncedFn();

        expect(fn).not.toHaveBeenCalled();

        vi.advanceTimersByTime(100);

        expect(fn).toHaveBeenCalledTimes(1);
      });

      it('should pass arguments to debounced function', () => {
        const fn = vi.fn();
        const debouncedFn = debounce(fn, 100);

        debouncedFn('arg1', 'arg2');
        vi.advanceTimersByTime(100);

        expect(fn).toHaveBeenCalledWith('arg1', 'arg2');
      });

      it('should use default wait time', () => {
        const fn = vi.fn();
        const debouncedFn = debounce(fn);

        debouncedFn();
        vi.advanceTimersByTime(250);

        expect(fn).toHaveBeenCalled();
      });
    });

    describe('throttle', () => {
      beforeEach(() => {
        vi.useFakeTimers();
      });

      afterEach(() => {
        vi.useRealTimers();
      });

      it('should throttle function calls', () => {
        const fn = vi.fn();
        const throttledFn = throttle(fn, 100);

        throttledFn();
        throttledFn();
        throttledFn();

        expect(fn).toHaveBeenCalledTimes(1);

        vi.advanceTimersByTime(100);
        throttledFn();

        expect(fn).toHaveBeenCalledTimes(2);
      });

      it('should pass arguments to throttled function', () => {
        const fn = vi.fn();
        const throttledFn = throttle(fn, 100);

        throttledFn('arg1', 'arg2');

        expect(fn).toHaveBeenCalledWith('arg1', 'arg2');
      });
    });
  });

  describe('Validation Utilities', () => {
    describe('isEmpty', () => {
      it('should return true for null/undefined', () => {
        expect(isEmpty(null)).toBe(true);
        expect(isEmpty(undefined)).toBe(true);
      });

      it('should return true for empty string', () => {
        expect(isEmpty('')).toBe(true);
        expect(isEmpty('   ')).toBe(true);
      });

      it('should return true for empty array', () => {
        expect(isEmpty([])).toBe(true);
      });

      it('should return true for empty object', () => {
        expect(isEmpty({})).toBe(true);
      });

      it('should return false for non-empty values', () => {
        expect(isEmpty('hello')).toBe(false);
        expect(isEmpty([1, 2])).toBe(false);
        expect(isEmpty({ a: 1 })).toBe(false);
        expect(isEmpty(0)).toBe(false);
        expect(isEmpty(false)).toBe(false);
      });
    });

    describe('isValidEmail', () => {
      it('should validate correct emails', () => {
        expect(isValidEmail('test@example.com')).toBe(true);
        expect(isValidEmail('user.name@domain.org')).toBe(true);
        expect(isValidEmail('user+tag@example.co.uk')).toBe(true);
      });

      it('should reject invalid emails', () => {
        expect(isValidEmail('notanemail')).toBe(false);
        expect(isValidEmail('missing@tld')).toBe(false);
        expect(isValidEmail('@nodomain.com')).toBe(false);
        expect(isValidEmail('spaces in@email.com')).toBe(false);
      });

      it('should handle null/undefined', () => {
        expect(isValidEmail(null)).toBe(false);
        expect(isValidEmail(undefined)).toBe(false);
        expect(isValidEmail('')).toBe(false);
      });
    });
  });

  describe('SharedUtils object', () => {
    it('should export all utilities', () => {
      expect(SharedUtils.formatDate).toBeDefined();
      expect(SharedUtils.formatTime).toBeDefined();
      expect(SharedUtils.formatDateTime).toBeDefined();
      expect(SharedUtils.formatRelativeTime).toBeDefined();
      expect(SharedUtils.truncate).toBeDefined();
      expect(SharedUtils.capitalize).toBeDefined();
      expect(SharedUtils.toTitleCase).toBeDefined();
      expect(SharedUtils.formatNumber).toBeDefined();
      expect(SharedUtils.formatCurrency).toBeDefined();
      expect(SharedUtils.debounce).toBeDefined();
      expect(SharedUtils.throttle).toBeDefined();
      expect(SharedUtils.isEmpty).toBeDefined();
      expect(SharedUtils.isValidEmail).toBeDefined();
    });
  });
});
