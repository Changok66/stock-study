# -*- coding: utf-8 -*-
"""
공정한 동전(앞면이 나올 확률 50%) 던지기 시뮬레이션

시행 횟수를 10, 40, 100, 1000, 10000번으로 늘려가며 각각 동전을 던져보고,
- 시행 횟수별 실제 앞면 비율을 표로 출력하고
- 시행 횟수가 늘어날수록 실제 비율이 이론값인 50%에 가까워지는(큰 수의 법칙)
  모습을 그래프로 그려서 확인한다.
"""

import numpy as np
import matplotlib.pyplot as plt

# matplotlib 기본 폰트는 한글을 지원하지 않아 그래프의 한글 라벨이
# 네모(□)로 깨져 보인다. 윈도우에 기본으로 설치되어 있는 "맑은 고딕"을
# 지정해 한글이 정상적으로 표시되도록 한다.
plt.rcParams["font.family"] = "Malgun Gothic"
# 한글 폰트 사용 시 마이너스(-) 기호가 깨지는 문제를 방지한다.
plt.rcParams["axes.unicode_minus"] = False


def toss_coins(n_tosses: int, seed: int | None = None) -> float:
    """
    공정한 동전을 n_tosses번 던져서 앞면이 나온 비율(%)을 반환한다.

    - np.random.choice를 이용해 "앞면"(1) 또는 "뒷면"(0)을 각각 50% 확률로 뽑는다.
    - seed를 지정하면 매번 같은 결과가 나오도록 난수를 고정할 수 있다.
      (seed=None이면 실행할 때마다 다른 난수를 사용한다.)
    """
    rng = np.random.default_rng(seed)

    # 0 또는 1을 동일한 확률(p=0.5)로 n_tosses번 추출한다.
    # 1 = 앞면, 0 = 뒷면 으로 정의한다.
    results = rng.choice([0, 1], size=n_tosses, p=[0.5, 0.5])

    # 앞면(1)이 나온 횟수의 합을 전체 시행 횟수로 나누면 앞면이 나온 비율이 된다.
    head_count = results.sum()
    head_ratio_percent = head_count / n_tosses * 100

    return head_ratio_percent


def run_simulations(trial_counts: list[int], seed: int | None = 42) -> list[float]:
    """
    trial_counts에 담긴 각 시행 횟수(10, 40, 100, 1000, 10000...)에 대해
    동전 던지기 시뮬레이션을 실행하고, 각 결과(앞면 비율 %)를 리스트로 반환한다.

    seed 값을 고정해 두면 스크립트를 여러 번 실행해도 동일한 결과가 재현되어
    디버깅이나 결과 비교가 쉬워진다. seed를 None으로 바꾸면 실행할 때마다
    다른(진짜 무작위) 결과를 얻을 수 있다.
    """
    head_ratios = []

    for i, n in enumerate(trial_counts):
        # 시행마다 조금씩 다른 seed를 사용해, 같은 seed로 인해 결과가
        # 서로 완전히 동일한 패턴이 되는 것을 방지한다.
        trial_seed = None if seed is None else seed + i
        ratio = toss_coins(n, seed=trial_seed)
        head_ratios.append(ratio)

    return head_ratios


def print_result_table(trial_counts: list[int], head_ratios: list[float]) -> None:
    """
    시행 횟수별 실제 앞면 비율을 보기 좋은 표 형태로 콘솔에 출력한다.
    이론적으로 기대되는 값(50%)과의 차이(오차)도 함께 보여준다.
    """
    print("=" * 50)
    print(f"{'시행 횟수':>10} | {'앞면 비율(%)':>12} | {'50%와의 오차':>12}")
    print("-" * 50)

    for n, ratio in zip(trial_counts, head_ratios):
        error = abs(ratio - 50)
        print(f"{n:>10,} | {ratio:>11.2f}% | {error:>11.2f}%p")

    print("=" * 50)


def plot_convergence(trial_counts: list[int], head_ratios: list[float]) -> None:
    """
    시행 횟수(x축)가 늘어날수록 실제 앞면 비율(y축)이 이론값인 50%에
    가까워지는 모습을 선 그래프로 그린다.

    - x축은 10 ~ 10000까지 값의 범위가 매우 넓기 때문에(1000배 차이)
      로그 스케일(log scale)을 사용해야 각 지점이 겹치지 않고 잘 구분되어 보인다.
    - 실제 앞면 비율은 파란색 실선 + 원형 마커로, 이론값 50% 기준선은
      회색 점선으로 그려 두 정보가 색만으로 헷갈리지 않고 형태로도 구분되게 한다.
    """
    fig, ax = plt.subplots(figsize=(8, 5))

    # 이론값(50%) 기준선을 먼저 그려서 배경 역할을 하게 한다.
    ax.axhline(
        y=50,
        color="#888888",
        linestyle="--",
        linewidth=2,
        label="이론적 확률 (50%)",
    )

    # 실제 시뮬레이션 결과(시행 횟수별 앞면 비율)를 선 + 마커로 그린다.
    ax.plot(
        trial_counts,
        head_ratios,
        color="#2563eb",  # 진한 파란색: 실제 결과 계열임을 나타내는 주 색상
        marker="o",
        markersize=8,
        linewidth=2,
        label="실제 앞면 비율",
    )

    # 각 데이터 포인트 위에 정확한 수치를 직접 라벨로 표시해 표를 보지 않아도
    # 그래프만으로 값을 바로 읽을 수 있게 한다.
    for n, ratio in zip(trial_counts, head_ratios):
        ax.annotate(
            f"{ratio:.1f}%",
            xy=(n, ratio),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color="#1e3a8a",
        )

    # x축 값 범위가 10~10000으로 넓으므로 로그 스케일을 사용한다.
    ax.set_xscale("log")
    ax.set_xticks(trial_counts)
    ax.set_xticklabels([f"{n:,}" for n in trial_counts])

    ax.set_xlabel("시행 횟수 (로그 스케일)")
    ax.set_ylabel("앞면이 나온 비율 (%)")
    ax.set_title("동전 던지기 시행 횟수에 따른 앞면 비율 수렴 (큰 수의 법칙)")

    # y축은 0~100% 전체가 아니라 50% 근처가 잘 보이도록 적당한 범위로 제한한다.
    ax.set_ylim(0, 100)

    # 보조 격자를 옅게 그려 값을 읽기 쉽게 하되, 데이터보다 시선을 끌지 않게 한다.
    ax.grid(True, which="both", linestyle=":", linewidth=0.7, alpha=0.5)

    ax.legend(loc="upper right")

    fig.tight_layout()

    # 그래프를 이미지 파일로 저장한다. (화면 출력 없이도 결과를 확인할 수 있도록)
    output_path = "coin_simulation_result.png"
    fig.savefig(output_path, dpi=150)
    print(f"\n그래프를 '{output_path}' 파일로 저장했습니다.")

    # 로컬 환경에서 직접 실행할 경우 화면에도 그래프를 띄워서 보여준다.
    plt.show()


def main() -> None:
    # 시뮬레이션을 진행할 시행 횟수 목록
    trial_counts = [10, 40, 100, 1000, 10000]

    # 각 시행 횟수에 대해 동전 던지기 시뮬레이션 실행
    head_ratios = run_simulations(trial_counts, seed=42)

    # 결과를 표로 출력
    print_result_table(trial_counts, head_ratios)

    # 결과를 그래프로 시각화
    plot_convergence(trial_counts, head_ratios)


if __name__ == "__main__":
    main()
