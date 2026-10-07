import json
import unittest
from types import SimpleNamespace
from unittest import mock

import requests

from src.core.reviews import evaluate_comments
from src.core.signer import Signer
from src.utils.config import Config


def comments_from(texts):
    """构造不同用户发表的公开评论，避免测试样本被去重规则过滤。"""
    return [{"content": text, "user": {"userId": index + 1}} for index, text in enumerate(texts)]


class CommentEvaluationTest(unittest.TestCase):
    def test_score_tag_and_summary_follow_public_opinions(self):
        cases = (
            (["歌词走心", "歌词有共鸣", "歌词空洞"], "4", "4-A-1", "正面2条、负面1条"),
            (["旋律很单调", "这首歌难听", "不好听"], "2", "2-B-1", "正面0条、负面3条"),
            (["唱功惊艳", "演唱出色", "唱功很差", "唱得不好"], "3", "3-C-1", "正面2条、负面2条"),
        )
        for texts, score, tag, counts in cases:
            with self.subTest(texts=texts):
                result = evaluate_comments(comments_from(texts))
                self.assertEqual(result[:2], (score, tag))
                self.assertIn(counts, result[2])
                self.assertIn("公开评论", result[2])

    def test_noise_mixed_opinions_and_insufficient_evidence_are_ignored(self):
        texts = ["想起前任，很难过", "生日快乐支持你", "不是难听", "不跑调", "旋律好听但歌词空洞"]
        self.assertIsNone(evaluate_comments(comments_from(texts)))
        self.assertIsNone(evaluate_comments(comments_from(["好听", "耐听"])))
        self.assertIsNone(evaluate_comments([None, {}, {"content": 123}, {"content": "好听"}]))

    def test_duplicates_and_repeat_users_do_not_create_a_consensus(self):
        comments = comments_from(["好听", " 好 听 ", "耐听", "旋律优美"])
        comments[-1]["user"]["userId"] = comments[-2]["user"]["userId"]
        self.assertIsNone(evaluate_comments(comments))

    def test_negated_praise_is_not_counted_as_positive(self):
        for text in ("不好听", "不太好听", "不怎么好听", "不耐听", "歌词没有共鸣", "歌词不走心"):
            with self.subTest(text=text):
                result = evaluate_comments(comments_from([f"{text}，评价{index}" for index in range(3)]))
                self.assertEqual(result[0], "2")
                self.assertIn("正面0条、负面3条", result[2])

    def test_double_negations_and_negated_attributes_are_treated_as_uncertain(self):
        texts = ["不是不好听", "没有跑调", "不算难听", "唱功不出色", "歌词不感人", "旋律不优美"]
        self.assertIsNone(evaluate_comments(comments_from(texts)))


class SignerCommentRatingTest(unittest.TestCase):
    def make_signer(self, strategy=0):
        """构造离线评分环境；保留明文请求以检查提交内容，不访问外部服务。"""
        session = mock.Mock()
        session.cookies = {"__csrf": "test-csrf"}
        session.request.return_value.json.return_value = {
            "code": 200,
            "hotComments": comments_from(["好听", "旋律耐听", "演唱惊艳"]),
            "comments": comments_from(["好听"]),
        }
        session.post.return_value.json.return_value = {"code": 200}
        config = SimpleNamespace(
            get=lambda key, default=None: {"score": strategy, "rate_limit_retries": 1}.get(key, default),
            get_wait_time=lambda: 0,
            get_http_timeout=lambda: 1,
        )
        signer = Signer(session, "task-id", mock.Mock(), config)
        signer._get_params = mock.Mock(side_effect=json.dumps)
        signer._get_enc_sec_key = mock.Mock(return_value="test-key")
        return signer

    def test_comments_are_fetched_once_and_the_same_evaluation_is_retried(self):
        signer = self.make_signer()
        limited = mock.Mock()
        limited.json.return_value = {"code": 500, "message": "操作频繁"}
        success = mock.Mock()
        success.json.return_value = {"code": 200}
        signer.session.post.side_effect = [limited, success]
        work = {"id": 100, "resourceId": 200, "name": "测试歌曲", "authorName": "作者"}

        with mock.patch("src.core.signer.time.sleep"):
            signer.sign(work, is_extra=True)

        signer.session.request.assert_called_once()
        request = signer.session.request.call_args.kwargs
        self.assertTrue(request["url"].endswith("R_SO_4_200"))
        self.assertEqual(request["timeout"], 1)
        self.assertEqual(json.loads(request["data"]["params"])["rid"], "200")
        submissions = [json.loads(call.kwargs["data"]["params"]) for call in signer.session.post.call_args_list]
        self.assertEqual(len(submissions), 2)
        self.assertEqual(submissions[0], submissions[1])
        self.assertEqual(submissions[0]["score"], "4")
        self.assertEqual(submissions[0]["tags"], "4-B-1")
        self.assertIn("参考3条公开评论", submissions[0]["comment"])
        self.assertIs(submissions[0]["syncYunCircle"], False)
        self.assertIs(submissions[0]["syncComment"], False)
        self.assertEqual(submissions[0]["extraResource"], "true")

    def test_unavailable_comments_fall_back_without_fabricating_text(self):
        for payload in ({"code": 403}, {"code": 200, "comments": []}, {"code": 200, "comments": None}, []):
            with self.subTest(payload=payload):
                signer = self.make_signer()
                signer.session.request.return_value.json.return_value = payload
                result = signer._get_evaluation({"resourceId": 200, "name": "测试"})
                self.assertEqual(result, ("3", "3-A-1", ""))
                signer.logger.warning.assert_called_once()

        signer = self.make_signer()
        signer.session.request.side_effect = requests.Timeout("超时")
        self.assertEqual(signer._get_evaluation({"resourceId": 200, "name": "测试"}), ("3", "3-A-1", ""))

    def test_invalid_song_identifiers_are_not_used_for_comment_requests(self):
        for work in ({"id": 100}, {"resourceId": "../../other"}, {"resourceId": 0}, {"resourceId": 200, "resourceType": "MV"}):
            with self.subTest(work=work):
                signer = self.make_signer()
                self.assertEqual(signer._get_evaluation({"name": "测试", **work}), ("3", "3-A-1", ""))
                signer.session.request.assert_not_called()

    def test_legacy_ranges_do_not_depend_on_language_or_fetch_comments(self):
        for strategy in range(1, 5):
            with self.subTest(strategy=strategy):
                signer = self.make_signer(strategy)
                with mock.patch("src.core.signer.random.randint", return_value=strategy):
                    chinese = signer._get_evaluation({"name": "中文", "authorName": "作者"})
                    english = signer._get_evaluation({"name": "Song", "authorName": "Author"})
                self.assertEqual(chinese, english)
                self.assertEqual(chinese[0], str(strategy))
                signer.session.request.assert_not_called()

    def test_invalid_strategies_are_rejected(self):
        for strategy in (-1, 5, True, 2.5, "3"):
            with self.subTest(strategy=strategy):
                signer = self.make_signer(strategy)
                with self.assertRaisesRegex(ValueError, "score 必须是"):
                    signer._get_evaluation({"name": "测试"})
                signer.session.request.assert_not_called()

    def test_default_strategy_enables_comments(self):
        config = {}
        Config._apply_defaults(None, config)
        self.assertEqual(config["score"], 0)


if __name__ == "__main__":
    unittest.main()
