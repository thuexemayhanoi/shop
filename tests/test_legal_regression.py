#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legal-truth regression gate tests (Law 36/2024, TT 38/2024, ND 168/2024)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from article_lib import check_legal_regressions  # noqa: E402


class LegalRegressionTest(unittest.TestCase):
    def _fail(self, text):
        return check_legal_regressions(text)

    def test_motorcycle_outside_area_90_80_rejected(self):
        self.assertTrue(self._fail(
            "Ngoài khu đông dân cư bạn được chạy tối đa 90 km/h trên đường đôi."))

    def test_motorcycle_outside_area_80_before_phrase_rejected(self):
        self.assertTrue(self._fail(
            "Mức 80 km/h áp dụng ngoài khu đông dân cư cho đường hai chiều."))

    def test_expressway_100_rejected(self):
        self.assertTrue(self._fail(
            "Trên đường cao tốc, xe mô tô hai bánh được chạy tối đa 100 km/h."))

    def test_a2_licence_rejected(self):
        self.assertTrue(self._fail(
            "Xe từ 125 cm khối đến dưới 175 cm khối đòi hỏi giấy phép lái xe hạng A2."))

    def test_blanket_idp_exchange_rejected(self):
        self.assertTrue(self._fail(
            "Giấy phép lái xe quốc tế luôn phải hợp pháp hóa hoặc đổi sang giấy phép Việt Nam."))

    def test_correct_claims_pass(self):
        ok = ("Ngoài khu đông dân cư xe mô tô tối đa 70 km/h trên đường đôi, "
              "60 km/h đường hai chiều không phân cách. Xe máy không được đi vào "
              "đường cao tốc. Xe trên 125 cm khối cần bằng hạng A. Giấy phép lái "
              "xe quốc tế được dùng theo điều ước quốc tế, kèm giấy phép quốc gia "
              "còn hiệu lực.")
        self.assertEqual(self._fail(ok), [])


if __name__ == "__main__":
    unittest.main()
